"""Support for the FR-AGT-14b store and ticker tests (interface: services/api/tests/API_FR_AGT_14b.md).

Package-unique module name, like `schedule_support.py`: every test directory has its own conftest.py. It builds on
`schedule_support` (Clock, the constants, the OIDC fake) and adds only what 14b needs: a record factory that carries
the snapshot fields, a store rig that runs the same cases against the in-memory store and (under `-m emulator`) the
Firestore store, and a few starters. No network and no sleeps; the Firestore rig exists only when the emulator
fixture does, and never opens a live client.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from schedule_support import KOLKATA_MON_0900, MON_0330Z, OWNER, WEEK, Clock, FakeFlags, FakeRunStarter
from tilo_harness.schedule import Schedule, Ticker
from tilo_harness.schedule_store import (
    FirestoreScheduleStore,
    InMemoryScheduleStore,
)

__all__ = [
    "MON_0330Z",
    "OWNER",
    "WEEK",
    "APPROVED_BRIEF",
    "StoreRig",
    "TickRig",
    "make_record",
    "make_tick_rig",
    "memory_rig",
    "firestore_rig",
]

APPROVED_BRIEF = {
    "goal": "Summarise the weekly supplier prices for the operations lead.",
    "deliverables": [{"title": "Supplier summary", "format": "pdf"}],
    "audience": "Operations lead",
    "deadline": None,
    "constraints": [],
    "sources": [],
    "sensitivity": "business",
}
APPROVED_APPROACH = {"id": "quick", "label": "Quick scan", "credits": {"min": 30, "max": 45}}


def make_record(schedule_id: str = "sched_a", **overrides: Any) -> Schedule:
    """A weekly Monday 09:00 Asia/Kolkata schedule due at MON_0330Z with the owner's approved snapshot. If the builder
    wraps the snapshot instead of adding fields to `Schedule`, this factory is the one place that changes."""
    fields: dict[str, Any] = {
        "schedule_id": schedule_id,
        "owner_user_id": OWNER,
        "title": "Weekly supplier digest",
        "cadence": KOLKATA_MON_0900,
        "approved_brief_ref": "w_approved_1",
        "budget_cap": 40.0,
        "enabled": True,
        "next_due": MON_0330Z,
        "brief": dict(APPROVED_BRIEF),
        "approach": dict(APPROVED_APPROACH),
        "created_at": MON_0330Z - timedelta(days=1),
    }
    fields.update(overrides)
    return Schedule(**fields)


@dataclass
class StoreRig:
    kind: str  # "memory" | "firestore"
    store: Any
    clock: Clock | None  # the store's own clock: only the memory store can be driven; Firestore uses server time

    @property
    def is_memory(self) -> bool:
        return self.kind == "memory"

    def now(self) -> datetime:
        """The store's idea of now (the fake clock, or the wall clock for Firestore)."""
        return self.clock() if self.clock is not None else datetime.now(UTC)

    def add(self, *schedules: Schedule) -> None:
        for schedule in schedules:
            assert self.store.create(schedule, max_per_owner=1000) is True


def memory_rig(start: datetime = MON_0330Z) -> StoreRig:
    clock = Clock(start)
    return StoreRig("memory", InMemoryScheduleStore(clock=clock), clock)


def firestore_rig() -> StoreRig:
    """A fresh org per test, so tests never see each other's documents. Needs the emulator fixture to have run."""
    store = FirestoreScheduleStore(project_id="demo-tilo", org_id=f"org_{secrets.token_hex(6)}")
    return StoreRig("firestore", store, None)


# --- the ticker over the real in-memory store -----------------------------------------------------------------------


class RaisingStarter(FakeRunStarter):
    """A starter that raises `exc_for(run)` for the runs it names (None means start normally)."""

    def __init__(self, clock: Callable[[], datetime] | None = None, *, exc_for: Callable[[Any], Exception | None]):
        super().__init__(clock)
        self._exc_for = exc_for

    def start(self, run: Any) -> str:
        exc = self._exc_for(run)
        if exc is not None:
            with self._lock:
                self.attempts.append(run)
            raise exc
        return super().start(run)


@dataclass
class TickRig:
    ticker: Ticker
    store: InMemoryScheduleStore
    starter: FakeRunStarter
    flags: FakeFlags
    clock: Clock
    alerts: list[tuple[str, dict[str, Any]]]


def make_tick_rig(
    schedules: list[Schedule] | None = None,
    *,
    starter: FakeRunStarter | None = None,
    now: datetime = MON_0330Z,
) -> TickRig:
    """A `Ticker` over the REAL in-memory store (same clock for both) and a fake starter."""
    clock = Clock(now)
    store = InMemoryScheduleStore(clock=clock)
    for schedule in [make_record()] if schedules is None else schedules:
        assert store.create(schedule, max_per_owner=1000) is True
    the_starter = starter if starter is not None else FakeRunStarter(clock)
    flags = FakeFlags()
    alerts: list[tuple[str, dict[str, Any]]] = []
    ticker = Ticker(
        store=store, starter=the_starter, flags=flags, clock=clock, alerts=lambda w, kw: alerts.append((w, kw))
    )
    return TickRig(ticker, store, the_starter, flags, clock, alerts)
