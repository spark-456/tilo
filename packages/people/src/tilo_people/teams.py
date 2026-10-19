"""Self-join and self-serve teams (ADR-0044; people.rules.md "Terms", PE-17, PE-20, PE-37).

`decide_team` ports `team_permits` of `tests/contracts/_teams_lib.py`, the reference check of
`contracts/fixtures/person.membership/crossref/`. The directory must be the WHOLE stored org (every person of the
server's org): the founding check compares an entry with every other entry for that team. Sessions (a full web or
mobile-web sign-in, never demo) and the bootstrap uid are the caller's. Deterministic, never raises, fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
        return r.actor == target["id"] and all(a is None or a["org_role"] != "owner" for a in assigners)
    return False
