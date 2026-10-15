"""SELF-SERVE-TEAMS INVITE-LINK (ADR-0046): the reference check for `contracts/fixtures/team_invite_link/crossref/`.

Not a test module. people.rules.md PE-38 (make, list and revoke a team invite link), PE-39 (redeem one) and PE-37 as
amended (a person leaves an entry they accepted, even one an org owner's link wrote). Membership is `_people_lib`'s
"Terms"; `remove_member` is `_teams_lib.team_permits`. A case is `{rule, note, now, org_id, persons, links, request}`:
`persons` is the stored directory and `links` the stored `team_invite_link` records of the org before the request.
`request` is `{actor, action, team, person, link, nonce_sha256, verified_email, record}`, null where unused:
`create_link` names `team` and `record` (what the create writes); `revoke_link` names `team` (the path's) and `link`;
`redeem_link` names `link` (the verified token's id), `nonce_sha256` (SHA-256 of the token's nonce) and
`verified_email` (the session's Google-verified address, or null); `remove_member` names `team` and `person`.
The signature, the token's format, the session kind and the answers are the API's tests (ADR-0046).
"""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime, timedelta
from typing import Any

import _people_lib as pl
import _teams_lib as tl

CASE_KEYS = {"rule", "note", "now", "org_id", "persons", "links", "request"}
REQUEST_KEYS = {"actor", "action", "team", "person", "link", "nonce_sha256", "verified_email", "record"}
RULES = ("PE-37", "PE-38", "PE-39")
LIFETIME = timedelta(days=7)  # PE-38: expires_at is at most 7 days after created_by.at
PENDING_CAP = 10  # PE-38: pending, unexpired links per team
NEEDS = {
    "create_link": {"team", "record"},
    "revoke_link": {"team", "link"},
    "redeem_link": {"link", "nonce_sha256"},  # verified_email too, which may be null
    "remove_member": {"team", "person"},
}
FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _plus(stamp: str, delta: timedelta) -> str:
    moved = datetime.strptime(stamp, FORMAT).replace(tzinfo=UTC) + delta
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


def _open(link: dict, now: str) -> bool:
    """Pending and not expired at `now` (expiry is derived, never stored)."""
    return link["status"] == "pending" and now < link["expires_at"]


def _manages(persons: dict, actor: str, team: str, now: str) -> bool:
    """An org owner, or a lead of `team` at `now` ("Terms")."""
    me = persons[actor]
    return me["org_role"] == "owner" or pl.is_lead(persons, actor, team, now)


def _create(case: dict, actor: str, team: str, record: dict) -> bool:
    persons, links, now = case["persons"], case["links"], case["now"]
    entries = [m for p in persons.values() for m in p["memberships"] if m["team"] == team]
    return (
        bool(entries)  # the team exists in the org
        and _manages(persons, actor, team, now)
        and all(m["assigned_by"]["at"] < now for m in entries if m.get("lead") is True)  # never a lead's instant
        and record["org_id"] == case["org_id"]
        and record["team"] == team
        and record["created_by"] == {"by": actor, "at": now}
        and now < record["expires_at"] <= _plus(now, LIFETIME)
        and record["status"] == "pending"
        and all(link["id"] != record["id"] for link in links)
        and sum(1 for link in links if link["team"] == team and _open(link, now)) < PENDING_CAP
    )


def _redeem(case: dict, actor: str, link: dict, request: dict) -> bool:
    persons, now, team = case["persons"], case["now"], link["team"]
    me = persons[actor]
    verified = request["verified_email"]
    if not (_open(link, now) and request["nonce_sha256"] == link["nonce_sha256"]):
        return False
    if verified is None or verified.lower() != me["email"].lower():
        return False
    if any(m["team"] == team for m in me["memberships"]) or len(me["memberships"]) >= tl.MEMBERSHIP_LIMIT:
        return False
    entry = {"team": team, "assigned_by": dict(link["created_by"]), "accepted_at": now}
    after = {**persons, actor: {**me, "memberships": [*me["memberships"], entry]}}
    before = [uid for uid in persons if pl.is_member(persons, uid, team, now)]
    return pl.counts(after, after[actor], entry, now) and all(pl.is_member(after, uid, team, now) for uid in before)


def link_permits(case: dict) -> bool:
    """True when PE-37 (as amended), PE-38 and PE-39 grant `case["request"]`."""
    request, persons = case["request"], case["persons"]
    actor, action = request["actor"], request["action"]
    me = persons.get(actor)
    if me is None or me["org_id"] != case["org_id"]:
        return False
    if action == "remove_member":
        keys = ("actor", "action", "person", "team")
        team_case = {**case, "request": {**{k: request[k] for k in keys}, "record": None}}
        del team_case["links"]
        return tl.team_permits(team_case)
    if action == "create_link":
        return _create(case, actor, request["team"], request["record"])
    link = next((x for x in case["links"] if x["id"] == request["link"]), None)
    if link is None or link["org_id"] != case["org_id"]:
        return False
    if action == "revoke_link":
        team = request["team"]
        return link["team"] == team and link["status"] == "pending" and _manages(persons, actor, team, case["now"])
    if action == "redeem_link":
        return _redeem(case, actor, link, request)
    return False


def case_shape_problems(repo_root: pathlib.Path, registry: Any, case: dict) -> list[str]:
    """Every part of a link case is shape-valid, and the request names what its action needs."""
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
    for i, link in enumerate(case["links"]):
        found += [f"links[{i}]: {m}" for m in pl.problems(repo_root, registry, "team_invite_link", link)]
    request = case["request"]
    if set(request) != REQUEST_KEYS or request["action"] not in NEEDS:
        return [*found, f"request must have keys {sorted(REQUEST_KEYS)} and an action in {sorted(NEEDS)}"]
    action = request["action"]
    used = {k for k in REQUEST_KEYS - {"actor", "action", "verified_email"} if request[k] is not None}
    if used != NEEDS[action]:
        found.append(f"{action} names exactly {sorted(NEEDS[action])}, got {sorted(used)}")
    if action != "redeem_link" and request["verified_email"] is not None:
        found.append("only redeem_link names verified_email")
    for key, schema, def_ in (
        ("actor", "common", "user_id"),
        ("team", "common", "team_id"),
        ("person", "common", "user_id"),
        ("link", "team_invite_link", "id"),
        ("nonce_sha256", "team_invite_link", "digest"),
        ("verified_email", "common", "email_address"),
        ("record", "team_invite_link", None),
    ):
        if request[key] is not None:
            found += [f"request.{key}: {m}" for m in pl.problems(repo_root, registry, schema, request[key], def_)]
    return found


def load_cases(repo_root: pathlib.Path, kind: str) -> list[tuple[pathlib.Path, dict]]:
    return [(p, pl.load_json(p)) for p in pl.fixture_files(repo_root, f"team_invite_link/crossref/{kind}")]
