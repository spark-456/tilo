"""Self-serve teams on tilo-api (SELF-SERVE-TEAMS, ADR-0044; people.rules.md "Terms", PE-17, PE-20, PE-37).

`GET /v1/teams` (my teams and pending invitations), `POST /v1/teams` (create one: the server mints the id and the
creator becomes its lead), `GET /v1/teams/{team}` (the roster, members only), `POST /v1/teams/{team}/invites` (a lead
or an org owner names a person by email; one answer whatever the address), `POST /v1/teams/{team}/accept` (only the
invited person) and `POST /v1/teams/{team}/members/{person_id}/remove` (a lead on their own team, an org owner, or a
person on their own entry: decline or leave). Every decision is `tilo_people.teams.decide_team` on the WHOLE stored
org directory and the verified session; every stamp is the session's person and the server clock (PE-19). Writes
need a full web or mobile_web sign-in that is not a demo session, count against `write_limit` (the people route
class), take closed JSON bodies and are a compare-and-set on the changed record, re-decided on a fresh directory after
a lost race. A lead never touches org roles, switches, limits, budgets or tools: those routes stay owner-only. No
model, no event (directory changes write none, ADR-0044 decision 7), and no name or address in a log.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import Field, field_validator
from tilo_people.access import project
from tilo_people.directory import Directory
from tilo_people.errors import NotFound, VersionConflict
from tilo_people.stores import PeopleStores, Stored
from tilo_people.teams import TeamRequest, decide_team, pending
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.people_writes import Empty, Refusal, _Closed, json_body, valid_email

router = APIRouter(route_class=_PeopleRoute)

Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]
Stores = Annotated[PeopleStores, Depends(deps.get_people_stores)]
Clock = Annotated[Callable[[], str], Depends(deps.get_clock)]
_TEAM = re.compile(r"tm_[0-9a-z_]{1,48}")
_PERSON = re.compile(r"u_[0-9A-Za-z_]{1,48}")
_SESSIONS = frozenset({"web", "mobile_web"})
_ATTEMPTS = 3
INVITED = {"status": "invited"}  # the one answer to an invitation (no existence oracle, PE-37)
REMOVED = {"status": "done"}  # the one answer to a remove by a lead or an owner (no membership oracle, PE-37)


class InviteIn(_Closed):
    email: Annotated[str, Field(max_length=254)]

    @field_validator("email")
    @classmethod
    def _address(cls, value: str) -> str:
        if not valid_email(value):
            raise ValueError("email")  # a 422 never names the value
        return value


def _forbidden() -> Refusal:
    return Refusal(403, "forbidden")


def _not_found() -> Refusal:
    return Refusal(404, "not_found")


def _session(principal: deps.Principal) -> None:
    """PE-37: a full web or mobile_web sign-in that is not a demo session (never email, a link or a world)."""
    full = principal.full_session is True and not principal.demo_session and principal.world_id is None
    if not (full and principal.channel in _SESSIONS):
        raise _forbidden()


def _team(team: str) -> str:
    if _TEAM.fullmatch(team) is None:
        raise _not_found()
    return team


def _snapshot(stores: PeopleStores) -> tuple[Directory, dict[str, Stored]]:
    try:
        rows = stores.persons.list(deps.ORG_ID)
    except NotImplementedError:
        raise
    except Exception:
        raise Refusal(503, "unavailable") from None
    return Directory.of(s.record for s in rows), {s.record["id"]: s for s in rows}


def _change(
    stores: PeopleStores,
    request: Callable[[Directory], TeamRequest | None],
    change: Callable[[dict[str, Any]], dict[str, Any]],
) -> bool:
    """Decide on a fresh whole-org directory, then compare-and-set the request's person. False: not granted (nothing
    written). A lost race reads again and decides again; a third loss is 409."""
    for _ in range(_ATTEMPTS):
        d, stored = _snapshot(stores)
        asked = request(d)
        if asked is None or not decide_team(asked, d):
            return False
        target = stored[asked.person or asked.actor]
        after = change(dict(target.record))
        if not conforms("person.schema.json", after):
            raise Refusal(409, "write_refused")  # e.g. the 8-membership limit reached between the read and here
        try:
            stores.persons.replace(after, expected_version=target.version)
            return True
        except VersionConflict:
            continue
        except NotFound:
            return False
        except Exception:
            raise Refusal(503, "unavailable") from None
    raise Refusal(409, "version_conflict", code="version_conflict")


def _entry_view(d: Directory, actor: str, m: Mapping[str, Any], now: str) -> dict[str, Any] | None:
    me = d.record(actor)
    if me is None:
        return None
    if d.counts(me, m, now):
        return {
            "team": m["team"],
            "lead": m.get("lead") is True and d.is_lead(actor, m["team"], now),
            "state": "member",
        }
    if pending(d, m, now):  # PE-20: the invited person reads the inviter's directory view while it is pending
        inviter = project("person", "directory", d.record(m["assigned_by"]["by"]) or {})
        return {"team": m["team"], "lead": False, "state": "pending", "invited_by": inviter}
    # An entry that counts for nothing (an invitation whose lead left, a stray lead flag): shown with no inviter, so
    # its person can remove it and free the slot (the 8-membership limit counts every stored entry).
    return {"team": m["team"], "lead": False, "state": "lapsed"}


@router.get("/v1/teams")
def my_teams(principal: Principal, stores: Stores, clock: Clock) -> dict[str, Any]:
    """The signed-in person's own teams and pending invitations; no record is the one 404."""
    _session(principal)
    now = clock()
    d, _ = _snapshot(stores)
    me = d.record(principal.user_id)
    if me is None:
        raise _not_found()
    rows = [_entry_view(d, principal.user_id, m, now) for m in me["memberships"]]
    return {"teams": [r for r in rows if r is not None], "you": principal.user_id}


def _after_the_team(d: Directory, team: str, now: str) -> str:
    """The invitation's stamp: the server clock, or 1 ms after the team's latest lead entry when the clock has not moved
    past it (a founding entry must stay strictly the earliest, "Terms" (2); a create and an invite in one millisecond
    would otherwise tie and found nothing)."""
    latest = max(
        (
            m["assigned_by"]["at"]
            for p in d.persons.values()
            for m in p["memberships"]
            if m["team"] == team and m.get("lead") is True
        ),
        default=None,
    )
    if latest is None or now > latest:
        return now
    later = datetime.strptime(latest, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) + timedelta(milliseconds=1)
    return later.strftime("%Y-%m-%dT%H:%M:%S.") + f"{later.microsecond // 1000:03d}Z"


@router.post("/v1/teams", status_code=201)
def create_team(
    _: Annotated[Empty, Depends(json_body(Empty))], principal: Principal, stores: Stores, clock: Clock
) -> dict[str, Any]:
    """Any person of the org creates a team: the id is minted here (96 random bits), the creator's founding entry is
    `{team, lead: true, assigned_by: creator at now}` (PE-37). The body is `{}`: nothing in it names a team."""
    _session(principal)
    now, team = clock(), "tm_" + secrets.token_hex(12)
    stamp = {"by": principal.user_id, "at": now}

    def add(me: dict[str, Any]) -> dict[str, Any]:
        return {**me, "memberships": [*me["memberships"], {"team": team, "lead": True, "assigned_by": stamp}]}

    asked = TeamRequest(principal.user_id, "create_team", deps.ORG_ID, now, team=team)
    if not _change(stores, lambda d: asked, add):
        raise _forbidden()
    return {"team": team, "lead": True, "state": "member"}


@router.get("/v1/teams/{team}")
def roster(team: str, principal: Principal, stores: Stores, clock: Clock) -> dict[str, Any]:
    """`read_roster`: a member of the team reads every member's id, display name and `lead` (PE-37); nothing of a
    pending invitation. Everyone else gets the one 404."""
    _session(principal)
    team, now = _team(team), clock()
    d, _ = _snapshot(stores)
    if not decide_team(TeamRequest(principal.user_id, "read_roster", deps.ORG_ID, now, team=team), d):
        raise _not_found()
    members = [
        {"id": uid, "display_name": p["display_name"], "lead": d.is_lead(uid, team, now)}
        for uid, p in d.persons.items()
        if d.is_member(uid, team, now)
    ]
    members.sort(key=lambda row: (not row["lead"], row["display_name"], row["id"]))
    return {"team": team, "members": members, "you": principal.user_id}


@router.post("/v1/teams/{team}/invites")
def invite(
    team: str, body: Annotated[InviteIn, Depends(json_body(InviteIn))], principal: Principal, stores: Stores,
    clock: Clock,
) -> dict[str, str]:  # fmt: skip
    """`add_member`: a lead of the team (a pending invitation) or an org owner (it counts at once) names a person by
    email, resolved here against the org's records. Not a lead or owner of THIS team: 403. Otherwise the answer is
    the same whether the address resolved, its person is already in the team or their limit is full."""
    _session(principal)
    team, now = _team(team), clock()
    d, _ = _snapshot(stores)
    me = d.record(principal.user_id)
    if me is None or not (me["org_role"] == "owner" or d.is_lead(principal.user_id, team, now)):
        raise _forbidden()
    wanted = body.email.lower()
    stamp = {"by": principal.user_id, "at": now}

    def asked(d: Directory) -> TeamRequest | None:
        found = [uid for uid, p in d.persons.items() if p["email"].lower() == wanted]
        if len(found) != 1:
            return None
        stamp["at"] = _after_the_team(d, team, now)
        return TeamRequest(principal.user_id, "add_member", deps.ORG_ID, now, person=found[0], team=team)

    def add(p: dict[str, Any]) -> dict[str, Any]:
        entry = {"team": team, "assigned_by": dict(stamp)}
        return {**p, "memberships": [*p["memberships"], entry]}

    try:
        _change(stores, asked, add)
    except Refusal as refused:
        if refused.status_code != 409:
            raise
    return INVITED


@router.post("/v1/teams/{team}/accept")
def accept(
    team: str, _: Annotated[Empty, Depends(json_body(Empty))], principal: Principal, stores: Stores, clock: Clock
) -> dict[str, Any]:
    """`accept_membership`: only the invited person sets `accepted_at` (the server clock) on their own pending entry."""
    _session(principal)
    team, now = _team(team), clock()
    asked = TeamRequest(principal.user_id, "accept_membership", deps.ORG_ID, now, person=principal.user_id, team=team)

    def accept_it(me: dict[str, Any]) -> dict[str, Any]:
        entries = [{**m, "accepted_at": now} if m["team"] == team else m for m in me["memberships"]]
        return {**me, "memberships": entries}

    if not _change(stores, lambda d: asked, accept_it):
        raise _not_found()
    return {"team": team, "lead": False, "state": "member"}


@router.post("/v1/teams/{team}/members/{person_id}/remove")
def remove(
    team: str, person_id: str, _: Annotated[Empty, Depends(json_body(Empty))], principal: Principal, stores: Stores,
    clock: Clock,
) -> dict[str, Any]:  # fmt: skip
    """`remove_member`: an org owner any entry; a lead of the team any entry of it but another person's lead entry; a
    person their own entry unless an org owner assigned it (decline, leave). A lead or an owner of the team gets the
    same status and body whether the person had a pending entry, any entry or no record (a lead reads nothing of a
    pending invitee, PE-20), and the write happens only when `decide_team` grants it. Anyone else: the one 403."""
    _session(principal)
    team, now = _team(team), clock()
    if _PERSON.fullmatch(person_id) is None:
        raise _forbidden()
    d, _rows = _snapshot(stores)
    me = d.record(principal.user_id)
    manages = me is not None and (me["org_role"] == "owner" or d.is_lead(principal.user_id, team, now))
    asked = TeamRequest(principal.user_id, "remove_member", deps.ORG_ID, now, person=person_id, team=team)

    def drop(p: dict[str, Any]) -> dict[str, Any]:
        return {**p, "memberships": [m for m in p["memberships"] if m["team"] != team]}

    try:
        removed = _change(stores, lambda d: asked, drop)
    except Refusal as refused:
        if not manages or refused.status_code != 409:
            raise
        removed = False
    if not (removed or manages):
        raise _forbidden()
    return REMOVED
