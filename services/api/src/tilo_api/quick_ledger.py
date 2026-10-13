"""COST-FAST-1b (BQ-COSTFAST-7): where a Quick call's spend is written so `GET /costs` can show it.

The Treasury is run-based and has no writable seam in tilo-api, so this is the seam: a `LedgerWriter` (one method,
`append`) that `deps.get_ledger_writer` hands out, unwired and failing closed like `deps.get_ledger`. Each person has
one pseudo run, `r_quick_<hash of uid>`: no world, event or task, so nothing animates. A Quick ask that was billed
appends one `commit` entry there for exactly the credits its FR-PA-19 allowance commit was. `MemoryLedger` is the
dev and test implementation; the Treasury's own ledger store (and #650's DevLedger) implement `append` the same way.
"""

from __future__ import annotations

import hashlib
import re
import threading
from datetime import datetime
from typing import Protocol

from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage

QUICK_STEP = "quick"
QUICK_TASK_TYPE = "quick_answer"  # the `by_task_type` label the web tells Quick spend by
_PROFILE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class LedgerWriter(Protocol):
    def append(self, entry: LedgerEntry) -> None: ...


def quick_run_id(uid: str) -> str:
    """The person's Quick pseudo run (common.schema.json run_id); stable, and it does not carry the uid."""
    return "r_quick_" + hashlib.sha256(uid.encode()).hexdigest()[:24]


def quick_entry(
    uid: str, org_id: str, at: datetime, credits: float, profile: str | None = None, tokens: tuple[int, int] = (0, 0)
) -> LedgerEntry:
    usage = Usage(profile, max(tokens[0], 0), max(tokens[1], 0)) if profile and _PROFILE.match(profile) else None
    return LedgerEntry("commit", quick_run_id(uid), uid, org_id, at, step=QUICK_STEP, credits=credits, usage=usage)


class MemoryLedger:
    """Thread-safe, in memory: the writer and, through `entries()`, the `get_ledger` reader of a dev or test app."""

    def __init__(self, limit: int | None = None) -> None:
        self._lock = threading.Lock()
        self._entries: list[LedgerEntry] = []
        self._ids: set[str] = set()
        self._limit = limit  # a demo session's cap: past it a write raises (the caller's write is best effort)

    def append(self, entry: LedgerEntry) -> None:
        self.append_once(None, entry)

    def append_once(self, entry_id: str | None, entry: LedgerEntry) -> None:
        """T3: the same entry id counts once (as `FirestoreTreasuryLedger.append_once`); no id is always new."""
        with self._lock:
            if entry_id is not None and entry_id in self._ids:
                return
            if self._limit is not None and len(self._entries) >= self._limit:
                raise OverflowError("the ledger is full")
            self._entries.append(entry)
            if entry_id is not None:
                self._ids.add(entry_id)

    def entries(self) -> list[LedgerEntry]:
        with self._lock:
            return list(self._entries)

    def entries_for(self, user_id: str) -> list[LedgerEntry]:
        with self._lock:
            return [e for e in self._entries if e.user == user_id]

    def erase_quick(self, uid: str) -> None:
        """FR-MEM-09: forget a person's Quick run."""
        run = quick_run_id(uid)
        with self._lock:
            self._entries = [e for e in self._entries if e.run != run]
