"""event.schema.json part-builders for this ticket's two side-effect events: `policy.changed`
(EV-03/EV-04, authz by the policy's owner) and `world.paused` (side_effect: false, authz null).
Every field not named by the caller is filled with the schema's honest default (null, "all",
"info") rather than left to guess -- no field here is invented business logic, it is the literal
shape `contracts/event.schema.json` and `contracts/event.rules.md` require of any event.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from tilo_api.deps import Store

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def now() -> str:
    """RFC 3339 UTC timestamp with exactly three fractional digits (common.schema.json#/$defs/timestamp)."""
    dt = datetime.now(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_ulid() -> str:
    """A fresh common.schema.json#/$defs/ulid-shaped id: not a real ULID's monotonic-time
    encoding (no clock injected here, per API_ST3a.md), just a value satisfying the contract's
    shape and uniqueness within a run."""
    first = secrets.choice("01234567")
    rest = "".join(secrets.choice(_CROCKFORD) for _ in range(25))
    return first + rest


def next_seq(store: Store, world_id: str) -> int:
    """Strictly increasing per world (EV-10), independent of insertion order or pre-seeded fixtures."""
    existing = store.events.get(world_id, [])
    return max((e["seq"] for e in existing), default=0) + 1


def _base_event(
    *,
    store: Store,
    world_id: str,
    type_: str,
    actor: str,
    target: str,
    summary: str,
    vis: Any,
    authz: dict | None,
    data: dict,
) -> dict:
    return {
        "v": "1.0",
        "id": new_ulid(),
        "seq": next_seq(store, world_id),
        "ts": now(),
        "world_id": world_id,
        "run_id": f"r_{world_id}",
        "type": type_,
        "actor": actor,
        "target": target,
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": summary[:140],
        "cause": None,
        "vis": vis,
        "authz": authz,
        "data": data,
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
    }


def policy_changed_event(
    *, store: Store, world_id: str, policy_id: str, change: str, level: str, owner: str, at: str
) -> dict:
    """EV-03/EV-04: side_effect, authz by person, authz.ref == the policy's owner."""
    return _base_event(
        store=store,
        world_id=world_id,
        type_="policy.changed",
        actor=owner,
        target=policy_id,
        summary=f"{owner} set policy {policy_id} to {level} ({change})",
        vis="all",
        authz={"by": "person", "ref": owner, "at": at},
        data={"policy_id": policy_id, "change": change, "level": level},
    )


def world_paused_event(*, store: Store, world_id: str, owner: str, channel: str | None) -> dict:
    """side_effect: false (events/registry.yaml): authz is null, vis is "all"."""
    return _base_event(
        store=store,
        world_id=world_id,
        type_="world.paused",
        actor=owner,
        target=world_id,
        summary="Pause all stopped every agent in this world",
        vis="all",
        authz=None,
        data={"reason": "pause_all", "channel": channel},
    )
