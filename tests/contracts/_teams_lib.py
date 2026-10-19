"""SELF-SERVE-TEAMS (ADR-0044): the reference check for `contracts/fixtures/person.membership/crossref/`.

Not a test module. people.rules.md "Terms" (as amended), PE-17 (self-join), PE-20 (the inviter's name) and PE-37
(self-serve teams). The Terms themselves are `_people_lib.is_member` and `is_lead`, shared with every people oracle.
A case is `{rule, note, now, org_id, persons, request}`: `org_id` is the server's org (`deps.ORG_ID`), `persons` the
stored directory before the request (it may be empty before anyone joined) and `request` is
`{actor, action, person, team, record}`, with null for what the action does not use. Sessions (full web or
mobile-web sign-in, never demo) and the bootstrap uid are the API's tests, not these files'.
"""

from __future__ import annotations

import pathlib
from typing import Any

import _people_lib as pl

CASE_KEYS = {"rule", "note", "now", "org_id", "persons", "request"}
REQUEST_KEYS = {"actor", "action", "person", "team", "record"}
RULES = ("PE-02", "PE-17", "PE-20", "PE-37")
MEMBERSHIP_LIMIT = 8  # person.schema.json memberships maxItems
NEEDS = {  # what each action names
    "read_roster": {"team"},
    "create_team": {"team"},
    "read_directory": {"person"},
    "set_org_role": {"person"},
    "add_member": {"person", "team"},
    "accept_membership": {"person", "team"},
    "remove_member": {"person", "team"},
    "set_lead": {"person", "team"},
    "self_join": {"record"},
}


def _pending(persons: dict, p: dict, m: dict, now: str) -> bool:
    """An invitation a lead of T made to `p` that `p` has not accepted yet (PE-37)."""
    a = persons.get(m["assigned_by"]["by"])
    return (
        a is not None
        and a["org_role"] != "owner"
        and m.get("accepted_at") is None
        and m["assigned_by"]["at"] <= now
        and pl.invited_by_a_lead(persons, m, now)
    )


def _self_join(case: dict, actor: str, record: dict) -> bool:
    """PE-17: one's own record, a member of the server's org with no team, stamped by oneself at the request."""
    return (
        actor not in case["persons"]
        and record["id"] == actor
        and record["org_id"] == case["org_id"]
        and record["org_role"] == "member"
        and record["memberships"] == []
        and record["created_by"] == {"by": actor, "at": case["now"]}
    )


def team_permits(case: dict) -> bool:
    """True when the amended Terms, PE-17, PE-20 and PE-37 grant `case["request"]`."""
    request, persons, now = case["request"], case["persons"], case["now"]
    action, actor, team = request["action"], request["actor"], request["team"]
    if action == "self_join":
        return _self_join(case, actor, request["record"])
    me = persons.get(actor)
    if me is None or me["org_id"] != case["org_id"]:
        return False
    owner = me["org_role"] == "owner"
    if action == "read_roster":
        return pl.is_member(persons, actor, team, now)
    if action == "create_team":
        used = any(m["team"] == team for p in persons.values() for m in p["memberships"])
        return not used and len(me["memberships"]) < MEMBERSHIP_LIMIT
    target = persons.get(request["person"])
    if target is None or target["org_id"] != me["org_id"]:
        return False
    if action == "set_org_role":
        return owner
    if action == "read_directory":
        invited_me = any(
            m["assigned_by"]["by"] == target["id"] and _pending(persons, me, m, now) for m in me["memberships"]
        )
        return actor == target["id"] or owner or pl.teammates(persons, actor, target["id"], now) or invited_me
    entries = [m for m in target["memberships"] if m["team"] == team]
    lead = pl.is_lead(persons, actor, team, now)
    if action == "set_lead":
        return owner
    if action == "add_member":
        return (owner or lead) and not entries and len(target["memberships"]) < MEMBERSHIP_LIMIT
    if action == "accept_membership":
        return actor == target["id"] and any(_pending(persons, target, m, now) for m in entries)
    if action == "remove_member":
        if not entries:
            return False
        if owner:
            return True
        if lead:  # any entry of their own team but another person's lead entry
            return actor == target["id"] or not any(m.get("lead") is True for m in entries)
        assigners = [persons.get(m["assigned_by"]["by"]) for m in entries]
        return actor == target["id"] and all(a is None or a["org_role"] != "owner" for a in assigners)
    return False


def case_shape_problems(repo_root: pathlib.Path, registry: Any, case: dict) -> list[str]:
    """Every part of a team crossref case is shape-valid, and the request names what its action needs."""
    if set(case) != CASE_KEYS:
        return [f"keys must be {sorted(CASE_KEYS)}, got {sorted(case)}"]
    found = [] if case["rule"] is None or case["rule"] in RULES else [f"rule must be null or one of {RULES}"]
    if not isinstance(case["note"], str) or not case["note"]:
        found.append("note must be a non-empty string")
    found += [f"now: {m}" for m in pl.problems(repo_root, registry, "common", case["now"], "timestamp")]
    found += [f"org_id: {m}" for m in pl.problems(repo_root, registry, "common", case["org_id"], "org_id")]
    for key, p in case["persons"].items():
        found += [f"persons.{key}: {m}" for m in pl.problems(repo_root, registry, "person", p)]
        if isinstance(p, dict) and p.get("id") != key:
            found.append(f"persons.{key}: the key must equal the person's id")
    request = case["request"]
    if set(request) != REQUEST_KEYS or request["action"] not in NEEDS:
        return [*found, f"request must have keys {sorted(REQUEST_KEYS)} and an action in {sorted(NEEDS)}"]
    found += [f"request.actor: {m}" for m in pl.problems(repo_root, registry, "common", request["actor"], "user_id")]
    used = {key for key in ("person", "team", "record") if request[key] is not None}
    if used != NEEDS[request["action"]]:
        found.append(f"{request['action']} names exactly {sorted(NEEDS[request['action']])}, got {sorted(used)}")
    for key, schema, def_ in (
        ("person", "common", "user_id"),
        ("team", "common", "team_id"),
        ("record", "person", None),
    ):
        if request[key] is not None:
            found += [f"request.{key}: {m}" for m in pl.problems(repo_root, registry, schema, request[key], def_)]
    return found


def load_cases(repo_root: pathlib.Path, kind: str) -> list[tuple[pathlib.Path, dict]]:
    return [(p, pl.load_json(p)) for p in pl.fixture_files(repo_root, f"person.membership/crossref/{kind}")]
