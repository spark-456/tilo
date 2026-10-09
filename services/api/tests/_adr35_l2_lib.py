"""Helpers for the ADR35-L2 tests (the durable Firestore outbox store): entries, a manual clock, and a rig that builds
the in-memory store and the Firestore store over the faithful fake in `_adr35_l2_fake.py`. Nothing here is logic."""

from __future__ import annotations

import copy
from typing import Any

from _adr35_l2_fake import OccFirestore
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors._time import add_seconds

T0 = "2026-10-09T10:00:00.000Z"
WORLD_A, WORLD_B = "w_adr35_a", "w_adr35_b"
OWNER = "u_owner"


class Clock:
    """The store's clock: set by the test, never by the wall."""

    def __init__(self, start: str = T0) -> None:
        self.now = start

    def __call__(self) -> str:
        return self.now

    def advance(self, seconds: float) -> str:
        self.now = add_seconds(self.now, seconds)
        return self.now


def outbox_id(n: int) -> str:
    return f"01JB5VQ{n:019d}"  # the ulid shape: 26 characters of Crockford base32


def entry(n: int = 1, *, world: str = WORLD_A, key: str | None = None, state: str = "queued", undo: int = 0) -> dict:
    scheduled_at = add_seconds(T0, undo)
    return {
        "id": outbox_id(n),
        "idempotency_key": key if key is not None else f"r_adr35:U{n}:send_email:{n}",
        "world_id": world,
        "run_id": "r_adr35",
        "action_type": "send_email",
        "connector": "gmail",
        "recipients": ["riya@example.com"],
        "attachments": [],
        "item": {"artifact_id": "art_reply_draft", "version": 1},
        "destination": "thread-supplier-1",
        "modifiers": [],
        "risk_tier": "T2",
        "authz": {"by": "person", "ref": OWNER, "at": T0},
        "undo_window_s": undo,
        "scheduled_at": scheduled_at,
        "state": "scheduled" if undo and state == "queued" else state,
        "created_at": T0,
    }


def transfer(n: int, world: str = WORLD_A) -> dict:
    return {"type": "data.transfer", "authz": {"by": "person", "ref": OWNER, "at": T0}, "world_id": world,
            "data": {"outbox_id": outbox_id(n)}}  # fmt: skip


def alert(n: int, world: str = WORLD_A) -> dict:
    return {"type": "alert.raised", "authz": None, "data": {"alert_id": outbox_id(n), "card_id": None},
            "world_id": world}  # fmt: skip


class Rig:
    """`make()` is a store as one tilo-api instance would hold it. In memory there is one store; on Firestore each
    call is a new instance over the same database, which is what a second Cloud Run instance is."""

    def __init__(self, kind: str, db: Any = None) -> None:
        """`kind` is `memory`, `firestore` (the fake) or `firestore-emulator` (a real client passed as `db`)."""
        self.kind, self.clock, self.db = kind, Clock(), db if db is not None else OccFirestore()
        self._memory = InMemoryOutboxStore(clock=self.clock)

    def make(self, clock: Any = None) -> Any:
        if self.kind == "memory":
            return self._memory
        from tilo_api.outbox_firestore import FirestoreOutboxStore  # noqa: PLC0415

        return FirestoreOutboxStore(self.db, clock=clock or self.clock)

    def put(self, store: Any, *entries: dict) -> None:
        for e in entries:
            assert store._insert_if_absent(copy.deepcopy(e)) is True

    def claim(self, store: Any, n: int, holder: str = "holder-1", skew: float = 0) -> dict | None:
        return store._claim_for_sending(outbox_id(n), holder, self.clock(), 30, skew)
