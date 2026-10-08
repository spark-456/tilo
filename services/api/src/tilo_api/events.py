"""Unstamped event.schema.json parts for FR-HIL-07's two side-effect types, plus plain policy-record
helpers. The event writer (the harness, PRD 15.3) alone stamps seq, ts, run_id and trace. Each part
carries its own `id`, minted once when enqueued and resent unchanged on every retry: the idempotency
key EventWriter.append dedupes on (EV-10). Pure functions: no locking, no I/O.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # common.schema.json#/$defs/ulid's alphabet


def now() -> str:
    """RFC 3339 UTC timestamp, exactly three fractional digits (common.schema.json#/$defs/timestamp)."""
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_part_id() -> str:
    """A fresh id matching common.schema.json#/$defs/ulid's pattern. Only uniqueness matters;
    ordering is the writer's stamped `seq`."""
    return _ulid(uuid.uuid4().int)


def stable_part_id(*key: str) -> str:
    """The same id for the same key, in the ulid shape: an event that every loader would write writes once (EV-10)."""
    return _ulid(int.from_bytes(hashlib.sha256("\x1f".join(key).encode()).digest(), "big"))


def _ulid(n: int) -> str:
    n %= 32**25
    body = []
    for _ in range(25):
        n, r = divmod(n, 32)
        body.append(_CROCKFORD[r])
    return "0" + "".join(reversed(body))


def policy_vis(policy: dict, world_districts: dict[str, Any] | None) -> Any:
    """EV-13: the intersection of scope.districts with the target world's layout. A missing or
    malformed scope, no layout, or an empty intersection falls back to "all"; never raises."""
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
    """A policy reading L1 is left alone only when its own last history entry agrees (no silent
    history repair)."""
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
    """Always appends a fresh history entry, never rewrites one; tolerates missing or malformed
    history and level."""
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


def world_failed_part(world_id: str, reason: str, run_id: str) -> dict:
    """The one `world.failed` of a restart: the run that held this world is gone (ADR-0026 decision 5). Its id comes
    from the world and its run, so two processes loading the world at once write one."""
    return {
        "id": stable_part_id("world.failed", world_id, run_id), "type": "world.failed", "actor": "system",
        "target": world_id, "level": None, "district": None, "item": None, "severity": "blocked", "credits": 0,
        "cause": None, "vis": "all", "authz": None, "summary": f"Stopped: {reason}"[:140],
        "data": {"reason": reason, "unit": None},
    }  # fmt: skip


def world_paused_part(*, part_id: str, world_id: str, actor: str, channel: str | None) -> dict:
    return {
        "id": part_id,
        "type": "world.paused",
        "actor": actor,
        "target": world_id,
        "summary": "Pause all stopped every agent in this world",
        "vis": "all",
        "authz": None,
        "data": {"reason": "pause_all", "channel": channel},
    }
