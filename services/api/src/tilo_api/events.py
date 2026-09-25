"""Unstamped event.schema.json *parts* for this ticket's two side-effect types (PI-18: the
event writer -- standing in for the harness, PRD 15.3 -- is the only one that stamps `id`,
`seq`, `ts`, `run_id` and `trace`; tilo-api never does). Also `now()`, used only for the plain
dict fields tilo-api itself owns (`policy["history"]`, `policy["changed_by"]`) -- never to stamp
an event's own `ts`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def now() -> str:
    """RFC 3339 UTC timestamp with exactly three fractional digits (common.schema.json#/$defs/timestamp)."""
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def policy_vis(policy: dict) -> Any:
    """EV-13 (round-2 finding): a policy's policy.changed announces to its own scope.districts
    when non-empty, else to everyone. Missing or malformed scope/scope.districts is unrestricted."""
    scope = policy.get("scope")
    if isinstance(scope, dict):
        districts = scope.get("districts")
        if isinstance(districts, list) and districts:
            return list(districts)
    return "all"


def policy_changed_part(*, policy_id: str, change: str, owner: str, at: str, vis: Any) -> dict:
    return {
        "type": "policy.changed",
        "actor": owner,
        "target": policy_id,
        "summary": f"{owner} set policy {policy_id} to L1 ({change})"[:140],
        "vis": vis,
        "authz": {"by": "person", "ref": owner, "at": at},
        "data": {"policy_id": policy_id, "change": change, "level": "L1"},
    }


def world_paused_part(*, world_id: str, owner: str, channel: str | None) -> dict:
    return {
        "type": "world.paused",
        "actor": owner,
        "target": world_id,
        "summary": "Pause all stopped every agent in this world",
        "vis": "all",
        "authz": None,
        "data": {"reason": "pause_all", "channel": channel},
    }
