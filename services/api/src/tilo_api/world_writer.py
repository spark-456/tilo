"""`EventWriter` over the harness `WorldWriter` (PROD-WIRE, ADR-0026 decision 4).

One `WorldWriter` per world over a harness store (the events backend), the org `deps.ORG_ID`, and the `run_id` and
layout of the world's cached record, never the part's. `append` commits under the part's own `id`: a same-content
resend returns the committed event, other content raises `deps.EventRejected` (the harness one is mapped), and
`WriterBusy` passes through unchanged. The committed event joins `store.events[world]` unless it is already there: the
only cache write for events.
With a `ledger`, a committed event that costs credits also appends its Treasury `commit` entry under the event id
(PROD-WIRE 5a), after the cache write and outside the world's lock: a resend repeats it harmlessly, and a ledger failure
is logged by type, never failing the event write.

Until the run builds its layout the writer gets one with a single agent, `A_director` (EV-12 accepts the Director's
planning events); the adapter reopens a writer whose world's `run_id` or `layout` changed. `WriterBusy` from an emit or
an open reopens that world's writer once (an own lease may have lapsed while idle) and retries; a second one is raised.
`reopen()` closes every open writer, releasing its lease, and each reopens on its next append.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
import zlib
from collections.abc import Callable
from datetime import datetime
from typing import Any

from tilo_harness.validator import EventRejected as HarnessEventRejected
from tilo_harness.writer import WorldWriter, WriterBusy

from tilo_api import deps
from tilo_api.cost_entries import entry_from_cost_event

logger = logging.getLogger("tilo_api.world_writer")

# The writer's input only, never stored: one scope, `shared`, and the Director's id for the planning events.
PREPLAN_LAYOUT: dict[str, Any] = {
    "semantic": {"levels": [], "islands": [], "gates": [], "agents": [{"id": "A_director", "rank": "director"}]}
}
_WRITER_ID = "tilo-api"
_REOPEN_LOCK_WAIT_S = 1.0
_STRIPES = 256


class WorldWriterAdapter:
    def __init__(
        self,
        store: deps.Store,
        backend: Any,
        *,
        org_id: str = deps.ORG_ID,
        clock: Callable[[], datetime] | None = None,
        lease_s: float = 30.0,
        ledger: Any = None,
    ) -> None:
        self._store, self._backend, self._org_id, self._clock, self._lease_s = store, backend, org_id, clock, lease_s
        self._ledger = ledger  # anything with `append(entry, *, entry_id)`: the Treasury's durable ledger
        # world -> ((run_id, layout) it was opened for, its writer)
        self._open: dict[str, tuple[tuple[str, dict[str, Any] | None], WorldWriter]] = {}
        # A fixed table, so it never grows: a world takes the stripe of its id (two worlds sharing one only take turns;
        # nothing here ever holds two stripes, so they cannot deadlock).
        self._locks = [threading.RLock() for _ in range(_STRIPES)]
        self._guard = threading.Lock()

    def _lock(self, world_id: str) -> threading.RLock:
        return self._locks[zlib.crc32(world_id.encode()) % _STRIPES]

    def _writer(self, world_id: str, record: deps.WorldRecord) -> WorldWriter:
        """The world's open writer for the record's run and layout; a changed run or layout closes it and opens anew."""
        key = (record.run_id, record.layout)
        held = self._open.get(world_id)
        if held is not None and held[0] == key:
            return held[1]
        self._close(world_id)
        key = (record.run_id, copy.deepcopy(record.layout))  # a later change in place is a change
        writer = WorldWriter(
            self._backend, org_id=self._org_id, world_id=world_id, run_id=record.run_id,
            layout=key[1] or PREPLAN_LAYOUT, writer_id=_WRITER_ID, lease_s=self._lease_s, clock=self._clock,
        )  # fmt: skip
        writer.open()  # WriterBusy: nothing is held, and nothing is remembered
        self._open[world_id] = (key, writer)
        return writer

    def _close(self, world_id: str) -> None:
        held = self._open.pop(world_id, None)
        if held is not None:
            try:
                held[1].close()
            except Exception as exc:  # the lease then lapses by itself
                logger.warning("closing the writer of world %s failed (%s)", world_id, type(exc).__name__)

    def _emit(self, world_id: str, record: deps.WorldRecord, part: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "type",
            "actor",
            "target",
            "summary",
            "level",
            "district",
            "item",
            "severity",
            "cause",
            "authz",
            "trace",
        )
        fields: dict[str, Any] = {
            k: part.get(k) for k in keys
        }  # a missing one is the writer's default or its rejection
        try:
            return self._writer(world_id, record).emit(
                **fields,
                data=part.get("data", {}),
                credits=part.get("credits", 0),
                vis=part["vis"],
                event_id=part["id"],
            )
        except HarnessEventRejected as exc:
            raise deps.EventRejected(str(exc)) from exc

    def _record_cost(self, record: deps.WorldRecord, committed: dict[str, Any]) -> None:
        """A committed cost event becomes its ledger entry under the event id, so a resend of the event is a no-op there
        and repairs an append that failed. The ledger is never allowed to fail or undo the event write."""
        if self._ledger is None:
            return
        try:
            entry = entry_from_cost_event({**committed, "run_id": record.run_id}, record.owner)
            if entry is not None:
                self._ledger.append(entry, entry_id=committed["id"])
        except Exception as exc:  # the type only: a message may carry a value
            logger.warning("cost ledger append for event %s failed (%s)", committed.get("id"), type(exc).__name__)

    def append(self, world_id: str, part: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(part.get("id"), str) or part.get("vis") is None:
            raise deps.EventRejected("an event needs its own `id` and says who may see it (`vis`)")
        with self._lock(world_id):
            record = self._store.worlds.get(world_id)  # read under the world's lock
            if record is None:
                raise deps.EventRejected(f"unknown world {world_id!r}")
            try:
                committed = self._emit(world_id, record, part)
            except WriterBusy:  # an own lease lapsed while idle, or the head moved: reopen this world once, resend
                self._close(world_id)
                committed = self._emit(world_id, record, part)
            events = self._store.events.setdefault(world_id, [])
            if not events or committed["seq"] > events[-1]["seq"]:  # a resend returns an event already cached
                events.append(committed)
            result = copy.deepcopy(committed)
        self._record_cost(record, result)  # outside the world's lock: a slow ledger never delays its next event
        return result

    def reopen(self, budget_s: float | None = None) -> None:
        """Closes every open writer, releasing its lease; each reopens on its next append. A world whose lock another
        thread holds for more than `_REOPEN_LOCK_WAIT_S` is skipped, never waited for: its append is in flight. With
        `budget_s` the whole call (shutdown) stops waiting when it is spent; the leases left lapse by themselves."""
        with self._guard:
            worlds = list(self._open)
        end = None if budget_s is None else time.monotonic() + budget_s
        skipped = 0
        for world_id in worlds:
            if end is not None and time.monotonic() >= end:
                skipped += 1
                continue
            wait = _REOPEN_LOCK_WAIT_S if end is None else min(_REOPEN_LOCK_WAIT_S, max(0.0, end - time.monotonic()))
            lock = self._lock(world_id)
            if not lock.acquire(timeout=wait):
                skipped += 1
                continue
            try:
                self._close(world_id)
            finally:
                lock.release()
        if skipped:
            logger.warning("reopen skipped %d world(s) whose writer was busy", skipped)
