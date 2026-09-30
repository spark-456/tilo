"""Unstamped event.schema.json *parts* for FR-HIL-07's two side-effect types, plus the plain
policy-record helpers (PI-13, PI-18: the event writer -- standing in for the harness, PRD 15.3 --
is the only one that stamps `seq`, `ts`, `run_id` and `trace`; tilo-api never does). Each part
carries its own `id`, a ULID minted once when it is enqueued (issue #46) and resent unchanged on
every retry: the idempotency key EventWriter.append dedupes on (EV-10), never content and never
writer-instance identity. Pure functions only -- no locking, no writer I/O, no HTTP; dispatch.py
orchestrates these under its own per-world/per-policy locks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # common.schema.json#/$defs/ulid's alphabet


def now() -> str:
    """RFC 3339 UTC timestamp, exactly three fractional digits (common.schema.json#/$defs/timestamp)."""
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_part_id() -> str:
    """A fresh id matching common.schema.json#/$defs/ulid's pattern (`[0-7][0-9A-HJKMNP-TV-Z]{25}`).
    uuid4's 122 random bits comfortably cover this; only "practically unique" is needed here --
    monotonic ordering is the writer's own stamped `seq`, not this id's job."""
    n = uuid.uuid4().int % (32**25)
    body = []
    for _ in range(25):
        n, r = divmod(n, 32)
        body.append(_CROCKFORD[r])
    return "0" + "".join(reversed(body))


def policy_vis(policy: dict, world_districts: dict[str, Any] | None) -> Any:
    """EV-13: the intersection of scope.districts with the *target* world's own layout (a policy
    carries no world_id of its own). Missing/malformed scope, no layout, or an empty intersection
    fall back to "all". Never raises on a non-string or unhashable scope.districts entry
    (round-6/ST-3a-2, issue #38 item 1) -- filtering by `isinstance(d, str)` first keeps an
    unhashable value from ever reaching the `in world_districts` membership test."""
    if not world_districts:
        return "all"
    scope = policy.get("scope")
    districts = scope.get("districts") if isinstance(scope, dict) else None
    try:
        intersection = [d for d in (districts or []) if isinstance(d, str) and d in world_districts]
    except TypeError:
        intersection = []
    return intersection if intersection else "all"


def is_consistent_l1(policy: dict) -> bool:
    """True idempotency (round-3, "no silent history repair"): a policy reading level == "L1" is
    left alone only when its own last history entry agrees -- never merely because the field
    reads "L1"."""
    if policy.get("level") != "L1":
        return False
    history = policy.get("history")
    return (
        isinstance(history, list)
        and bool(history)
        and isinstance(history[-1], dict)
        and history[-1].get("level") == "L1"
    )


def apply_level_change(policy: dict, *, owner: str, change: str, at: str) -> None:
    """Fails safe on a missing/malformed history or level (round-1): always appends a fresh entry,
    never rewrites or drops what was already there."""
    history = policy.get("history")
    history = list(history) if isinstance(history, list) else []
    history.append({"by": owner, "at": at, "change": change, "level": "L1"})
    policy["history"] = history
    policy["level"] = "L1"
    policy["changed_by"] = {"by": owner, "at": at}


def policy_changed_part(*, part_id: str, policy_id: str, change: str, owner: str, at: str, vis: Any) -> dict:
    return {
        "id": part_id,
        "type": "policy.changed",
        "actor": owner,
        "target": policy_id,
        "summary": f"{owner} set policy {policy_id} to L1 ({change})"[:140],
        "vis": vis,
        "authz": {"by": "person", "ref": owner, "at": at},
        "data": {"policy_id": policy_id, "change": change, "level": "L1"},
    }


def world_paused_part(*, part_id: str, world_id: str, channel: str | None) -> dict:
    return {
        "id": part_id,
        "type": "world.paused",
        "actor": "system",
        "target": world_id,
        "summary": "Pause all stopped every agent in this world",
        "vis": "all",
        "authz": None,
        "data": {"reason": "pause_all", "channel": channel},
    }
