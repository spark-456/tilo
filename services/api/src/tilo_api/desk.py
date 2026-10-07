"""The Desk world (PE-12, BQ-PPL11B-11): one lazily created world per person that holds their own panel and nudge
events. Its ids are derived from the org and the person, so they never collide and fit the id limits; its events
carry `vis: "all"` and the world is never shared until ADR-0009."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass

from fastapi import HTTPException

from tilo_api.deps import Store, WorldRecord


@dataclass(frozen=True)
class DeskRef:
    world_id: str
    run_id: str


def ensure_desk(store: Store, *, org_id: str, user: str) -> DeskRef:
    """The person's Desk world, made on first use with the person as owner and no districts. 503 when its id is
    held by a world of someone else (never adopted, never overwritten)."""
    digest = hashlib.sha256(f"{org_id}:{user}".encode()).hexdigest()[:24]
    desk = DeskRef(f"w_desk_{digest}", f"r_desk_{digest}")
    held = store.worlds.setdefault(desk.world_id, WorldRecord(owner=user, districts={}, run_id=desk.run_id))
    if not isinstance(held, WorldRecord) or held.owner != user:
        raise HTTPException(status_code=503, detail="not_configured")
    return desk


def lock(store: Store, user: str) -> threading.Lock:
    """One lock per person's Desk run, kept on the Store instance like `grant_lock` (a user id has no ':', so it
    never meets an owner's grant lock): archive records and events of one run are appended one question at a time."""
    return store.grant_lock(f"desk:{user}")
