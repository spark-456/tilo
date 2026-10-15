"""Self-join and self-serve teams (ADR-0044; people.rules.md "Terms", PE-17, PE-20, PE-37).

`decide_team` ports `team_permits` of `tests/contracts/_teams_lib.py`, the reference check of
`contracts/fixtures/person.membership/crossref/`. The directory must be the WHOLE stored org (every person of the
server's org): the founding check compares an entry with every other entry for that team. Sessions (a full web or
mobile-web sign-in, never demo) and the bootstrap uid are the caller's. Deterministic, never raises, fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeGuard

from ._schema import is_timestamp, is_user_id, valid
from .directory import Directory

MEMBERSHIP_LIMIT = 8  # person.schema.json memberships maxItems
TEAM_ACTIONS = (
    "self_join",
    "create_team",
    "add_member",
    "accept_membership",
    "remove_member",
    "set_lead",
    "set_org_role",
    "read_roster",
    "read_directory",
)


@dataclass(frozen=True, repr=False)
class TeamRequest:
    actor: str  # the session's person
    action: str  # one of TEAM_ACTIONS
    org_id: str  # the server's org, never the request's
    now: str  # the server clock
    person: str | None = None  # the person acted on
    team: str | None = None  # the team acted on
    record: Mapping[str, Any] | None = None  # self_join: the record to be stored

    def __repr__(self) -> str:  # fixed words only
        return f"TeamRequest(action={self.action if self.action in TEAM_ACTIONS else '?'!r})"


def _is_team(value: Any) -> TypeGuard[str]:
    return valid("common.schema.json#/$defs/team_id", value)


def pending(d: Directory, m: Mapping[str, Any], now: str) -> bool:
    """`m` is an invitation a lead of its team made that its person has not accepted yet (PE-37)."""
    a = d.record(m["assigned_by"]["by"])
    return (
        a is not None
        and a["org_role"] != "owner"
        and m.get("accepted_at") is None
        and m["assigned_by"]["at"] <= now
        and d.invited_by_a_lead(m, now)
    )


def _self_join(r: TeamRequest, d: Directory) -> bool:
    rec = r.record
    return bool(
        isinstance(rec, Mapping)
        and valid("person.schema.json", rec)
        and d.record(r.actor) is None
        and rec["id"] == r.actor
        and rec["org_id"] == r.org_id
        and rec["org_role"] == "member"
        and rec["memberships"] == []
        and rec["created_by"] == {"by": r.actor, "at": r.now}
    )


def decide_team(r: TeamRequest, d: Directory) -> bool:
    """True when the amended Terms, PE-17, PE-20 and PE-37 grant `r`. Never raises."""
    try:
        return _decide(r, d) is True
    except Exception:
        return False


def _decide(r: TeamRequest, d: Directory) -> bool:
    if not (is_user_id(r.actor) and r.action in TEAM_ACTIONS and is_timestamp(r.now) and isinstance(r.org_id, str)):
        return False
    if r.action == "self_join":
        return _self_join(r, d)
    me, now, team = d.record(r.actor), r.now, r.team
    if me is None or me["org_id"] != r.org_id:
        return False
    owner = me["org_role"] == "owner"
    if r.action == "read_roster":
        return _is_team(team) and d.is_member(r.actor, team, now)
    if r.action == "create_team":
        used = any(m["team"] == team for p in d.persons.values() for m in p["memberships"])
        return _is_team(team) and not used and len(me["memberships"]) < MEMBERSHIP_LIMIT
    target = d.record(r.person)
    if target is None or target["org_id"] != me["org_id"]:
        return False
    if r.action == "set_org_role":
        return owner
    if r.action == "read_directory":
        invited_me = any(m["assigned_by"]["by"] == target["id"] and pending(d, m, now) for m in me["memberships"])
        return r.actor == target["id"] or owner or d.teammates(r.actor, target["id"], now) or invited_me
    if not _is_team(team):
        return False
    entries = [m for m in target["memberships"] if m["team"] == team]
    lead = d.is_lead(r.actor, team, now)
    if r.action == "set_lead":
        return owner
    if r.action == "add_member":
        return (owner or lead) and not entries and len(target["memberships"]) < MEMBERSHIP_LIMIT
    if r.action == "accept_membership":
        return r.actor == target["id"] and any(pending(d, m, now) for m in entries)
    if r.action == "remove_member":
        if not entries:
            return False
        if owner:
            return True
        if lead:  # any entry of their own team but another person's lead entry
            return r.actor == target["id"] or not any(m.get("lead") is True for m in entries)
        assigners = [d.record(m["assigned_by"]["by"]) for m in entries]
        return r.actor == target["id"] and all(
            a is None or a["org_role"] != "owner" or m.get("accepted_at") is not None
            for a, m in zip(assigners, entries, strict=True)
        )
    return False


@dataclass(frozen=True, repr=False)
class LinkRequest:
    actor: str
    action: str
    org_id: str
    now: str
    team: str | None = None
    link: str | None = None
    nonce_sha256: str | None = None
    verified_email: str | None = None
    record: Mapping[str, Any] | None = None

    def __repr__(self) -> str:
        action = self.action if self.action in ("create_link", "revoke_link", "redeem_link") else "?"
        return f"LinkRequest(action={action!r})"


def decide_link(r: LinkRequest, d: Directory, links: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]) -> bool:
    """PE-38/39 on the whole org directory and stored links; malformed input fails closed."""
    try:
        return _link_decision(r, d, links) is True
    except Exception:
        return False


def _link_decision(
    r: LinkRequest, d: Directory, links: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...]
) -> bool:
    if not (is_user_id(r.actor) and is_timestamp(r.now) and isinstance(r.org_id, str)):
        return False
    me = d.record(r.actor)
    if me is None or me["org_id"] != r.org_id:
        return False

    def manages(team: str) -> bool:
        return me["org_role"] == "owner" or d.is_lead(r.actor, team, r.now)

    if r.action == "create_link":
        team, rec = r.team, r.record
        if not (_is_team(team) and isinstance(rec, Mapping) and valid("team_invite_link.schema.json", rec)):
            return False
        entries = [m for p in d.persons.values() for m in p["memberships"] if m["team"] == team]
        later = (
            (datetime.strptime(r.now, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) + timedelta(days=7))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        return (
            bool(entries)
            and manages(team)
            and all(m["assigned_by"]["at"] < r.now for m in entries if m.get("lead") is True)
            and rec["org_id"] == r.org_id
            and rec["team"] == team
            and rec["created_by"] == {"by": r.actor, "at": r.now}
            and r.now < rec["expires_at"] <= later
            and rec["status"] == "pending"
            and all(link["id"] != rec["id"] for link in links)
            and sum(
                1
                for link in links
                if link["team"] == team and link["status"] == "pending" and r.now < link["expires_at"]
            )
            < 10
        )
    link = next((link for link in links if link["id"] == r.link), None)
    if link is None or not valid("team_invite_link.schema.json", link) or link["org_id"] != r.org_id:
        return False
    team = link["team"]
    if r.action == "revoke_link":
        return r.team == team and link["status"] == "pending" and manages(team)
    if r.action != "redeem_link":
        return False
    if not (
        link["status"] == "pending"
        and r.now < link["expires_at"]
        and r.nonce_sha256 == link["nonce_sha256"]
        and isinstance(r.verified_email, str)
        and r.verified_email.lower() == me["email"].lower()
    ):
        return False
    if any(m["team"] == team for m in me["memberships"]) or len(me["memberships"]) >= MEMBERSHIP_LIMIT:
        return False
    entry = {"team": team, "assigned_by": dict(link["created_by"]), "accepted_at": r.now}
    after = Directory.of(
        [*([p for uid, p in d.persons.items() if uid != r.actor]), {**me, "memberships": [*me["memberships"], entry]}]
    )
    joined = after.record(r.actor)
    return (
        joined is not None
        and after.counts(joined, entry, r.now)
        and all(after.is_member(uid, team, r.now) for uid in d.persons if d.is_member(uid, team, r.now))
    )
