"""The cached Google calendar of each person and the one render path (FR-CAL-08, FR-CAL-02). API_FR_CAL_08.md.

A store holds one `SyncState` per person (with the sealed sync token) and that person's Google-sourced
`calendar_entry` rows. `commit` is the only writer: atomic and compare-and-set, so two instances of one person
commit once. `agenda` is the read model of the cache and takes no provider: rendering a calendar makes no model
call (FR-CAL-08, PRD 4). Imports only the standard library, `_time` and `_schema`; logs nothing. Entries are
private to their owner (PE-04); `forget` deletes a person's state and entries together (PE-13, PE-16).
"""

from __future__ import annotations

import copy
import hashlib
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from ._schema import calendar_entry_validator
from ._time import format_ts, parse_ts

CALENDAR_ID = "primary"
MAX_AGENDA_SPAN = timedelta(days=31)


@dataclass(frozen=True)
class CalendarConnection:
    """Minted by `CalendarSync.register` from server-side records, never from a request."""

    user_id: str  # the owner of every entry this connection writes
    org_id: str
    world_id: str  # the person's Desk world, where calendar.synced goes (PE-12)
    connection_id: str  # "cc_" + 26 Crockford base32 characters
    registered_at: str


@dataclass(frozen=True)
class SyncState:
    connection: CalendarConnection
    generation: int  # +1 on every commit (sync or failure); the compare-and-set key
    sealed_token: bytes | None = field(repr=False)  # Kms ciphertext of the sync token; None: the next run is full
    next_due_at: str
    last_run_at: str | None
    failures: int  # failed runs in a row; 0 after a sync


def entry_id(user_id: str, event_id: str) -> str:
    seed = f"{user_id}\x00{CALENDAR_ID}\x00{event_id}".encode()
    return "ce_g" + hashlib.sha256(seed).hexdigest()[:40]


class CalendarStore(Protocol):  # Firestore later: one transaction per commit
    def add(self, state: SyncState) -> SyncState: ...  # stores it unless the user has one; returns the stored
    def get(self, user_id: str) -> SyncState | None: ...
    def user_ids(self) -> tuple[str, ...]: ...  # sorted
    def entries(self, user_id: str) -> tuple[dict[str, Any], ...]: ...  # copies, sorted by (start, id)
    def commit(
        self, expected: SyncState, new: SyncState, *, upserts: Sequence[dict[str, Any]], removals: Sequence[str]
    ) -> bool: ...
    def forget(self, user_id: str) -> None: ...


class InMemoryCalendarStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, SyncState] = {}
        self._entries: dict[str, dict[str, dict[str, Any]]] = {}

    def add(self, state: SyncState) -> SyncState:
        with self._lock:
            return self._states.setdefault(state.connection.user_id, state)

    def get(self, user_id: str) -> SyncState | None:
        with self._lock:
            return self._states.get(user_id)

    def user_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._states))

    def entries(self, user_id: str) -> tuple[dict[str, Any], ...]:
        with self._lock:
            rows = sorted(self._entries.get(user_id, {}).values(), key=lambda e: (e["start"], e["id"]))
            return tuple(copy.deepcopy(rows))

    def commit(
        self, expected: SyncState, new: SyncState, *, upserts: Sequence[dict[str, Any]], removals: Sequence[str]
    ) -> bool:
        conn = expected.connection
        if new.connection != conn or new.generation != expected.generation + 1:
            raise ValueError("commit: the new state must be the next generation of the same connection")
        rows = [copy.deepcopy(dict(row)) for row in upserts]
        for row in rows:  # all checked before anything is written
            if not calendar_entry_validator().is_valid(row):
                raise ValueError("commit: an entry breaks calendar_entry.schema.json")
            if (row["owner"], row["org_id"], row["source"]["kind"]) != (conn.user_id, conn.org_id, "google"):
                raise ValueError("commit: an entry is not a Google entry of this connection's owner and org")
        with self._lock:
            current = self._states.get(conn.user_id)
            if current is None or (current.connection.connection_id, current.generation) != (
                conn.connection_id,
                expected.generation,
            ):
                return False  # another instance committed first, or the person was forgotten
            held = self._entries.setdefault(conn.user_id, {})
            for removed in removals:
                held.pop(removed, None)
            held.update({row["id"]: row for row in rows})
            self._states[conn.user_id] = new
            return True

    def forget(self, user_id: str) -> None:
        with self._lock:
            self._states.pop(user_id, None)
            self._entries.pop(user_id, None)


def agenda(store: CalendarStore, user_id: str, *, start: str, end: str) -> tuple[dict[str, Any], ...]:
    """One `agenda_item` per accepted entry of `user_id` overlapping [start, end), sorted by (start, end, id).
    The caller passes the signed-in principal as `user_id` (PE-04). Reads the cache and nothing else."""
    low, high = format_ts(parse_ts(start)), format_ts(parse_ts(end))
    if low >= high or parse_ts(high) - parse_ts(low) > MAX_AGENDA_SPAN:
        raise ValueError("agenda: the range must be positive and at most 31 days")
    rows = []
    for e in store.entries(user_id):
        overlaps = e["end"] is not None and (e["start"] >= low if e["end"] == e["start"] else e["end"] > low)
        if e["owner"] == user_id and e["state"] == "accepted" and e["start"] < high and overlaps:
            rows.append(
                {
                    "start": e["start"],
                    "end": e["end"],
                    "all_day": e["all_day"],
                    "title": e["title"],
                    "kind": "event",
                    "source": {"kind": "calendar_entry", "id": e["id"]},
                    "state": "confirmed",
                    "shared": False,
                }
            )
    return tuple(sorted(rows, key=lambda r: (r["start"], r["end"], r["source"]["id"])))
