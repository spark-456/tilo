"""Test doubles for FR-AGT-14 (scheduled runs, "Clock Tower"). Interface: tests/API_FR_AGT_14.md.

Package-unique module name (same reason as `claim_race_support.py` and `hil_wait_support.py`: every test
directory in the repo has its own conftest.py). Nothing here is production logic. Every class is a fake of
an injected dependency of `tilo_harness.schedule`: the schedule store, the run starter, the flag store, the
OIDC verifier and the alert sink. No network, no sleeps, no paid calls; tokens are assembled at runtime.

The fakes are deliberately NOT forgiving: the run starter does not deduplicate by idempotency key and the
store does not hide a disabled schedule unless asked to, so a test passes only when `Ticker` itself keeps the
rules (exactly one run per slot, nothing early, nothing from a disabled schedule).
"""

from __future__ import annotations

import secrets
import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from tilo_harness.schedule import (
    Cadence,
    RunStart,
    Schedule,
    Ticker,
    slot_key,
)

# 2026-10-05 is a Monday. 03:30Z is Monday 09:00 in Asia/Kolkata (UTC+5:30, no DST).
MON_0330Z = datetime(2026, 10, 5, 3, 30, tzinfo=UTC)
WEEK = timedelta(days=7)

KOLKATA_MON_0900 = Cadence(weekday=0, hour=9, minute=0, tz="Asia/Kolkata")

OWNER = "u_owner"
PROJECT = "demo-tilo"
AUDIENCE = "https://tilo-harness-abc123-as.a.run.app"
SCHEDULE_SA = f"tilo-schedule-scheduler@{PROJECT}.iam.gserviceaccount.com"
GMAIL_SA = f"tilo-gmail-scheduler@{PROJECT}.iam.gserviceaccount.com"
TASKS_SA = f"tilo-tasks-invoker@{PROJECT}.iam.gserviceaccount.com"
API_SA = f"tilo-api@{PROJECT}.iam.gserviceaccount.com"
GOOGLE_ISSUER = "https://accounts.google.com"


class Clock:
    """Injected clock (`Callable[[], datetime]`, UTC-aware). Moves only when a test moves it, including
    backwards. Thread-safe so the concurrency tests can read it from many threads."""

    def __init__(self, start: datetime = MON_0330Z) -> None:
        self._now = start
        self._lock = threading.Lock()

    def __call__(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, when: datetime) -> None:
        with self._lock:
            self._now = when

    def advance(self, delta: timedelta | float) -> None:
        step = delta if isinstance(delta, timedelta) else timedelta(seconds=delta)
        with self._lock:
            self._now += step


def make_schedule(schedule_id: str = "sched_a", **overrides: Any) -> Schedule:
    """A weekly Monday 09:00 Asia/Kolkata schedule due at MON_0330Z, owned by u_owner."""
    fields: dict[str, Any] = {
        "schedule_id": schedule_id,
        "owner_user_id": OWNER,
        "title": "Weekly supplier digest",
        "cadence": KOLKATA_MON_0900,
        "approved_brief_ref": "w_approved_1",
        "budget_cap": 40.0,
        "enabled": True,
        "next_due": MON_0330Z,
        "last_slot": None,
        "last_world_id": None,
    }
    fields.update(overrides)
    return Schedule(**fields)


class MemoryScheduleStore:
    """In-memory `ScheduleStore` (API_FR_AGT_14.md). Atomic under a lock, like the Firestore transaction
    the production store runs. A claim is a marker held until `release` or `complete`; `next_due` moves
    only in `complete`."""

    def __init__(self, schedules: Iterable[Schedule] = (), *, due_ignores_enabled: bool = False) -> None:
        # due_ignores_enabled: a careless store that hands back (and lets a tick claim) disabled schedules too.
        self._lock = threading.Lock()
        self._rows: dict[str, Schedule] = {s.schedule_id: s for s in schedules}
        self._held: dict[str, datetime] = {}
        self._due_ignores_enabled = due_ignores_enabled
        self.claims_won: list[tuple[str, datetime]] = []
        self.claims_lost: list[tuple[str, datetime]] = []
        self.releases: list[tuple[str, datetime]] = []
        self.completions: list[tuple[str, datetime]] = []
        self.due_calls: list[tuple[datetime, int]] = []

    def add(self, schedule: Schedule) -> None:
        with self._lock:
            self._rows[schedule.schedule_id] = schedule

    def get(self, schedule_id: str) -> Schedule:
        with self._lock:
            return self._rows[schedule_id]

    def held(self) -> dict[str, datetime]:
        with self._lock:
            return dict(self._held)

    def due(self, now: datetime, limit: int) -> list[Schedule]:
        with self._lock:
            self.due_calls.append((now, limit))
            rows = [s for s in self._rows.values() if (s.enabled or self._due_ignores_enabled) and s.next_due <= now]
            rows.sort(key=lambda s: (s.next_due, s.schedule_id))
            return rows[:limit]

    def claim(self, schedule_id: str, due: datetime) -> bool:
        with self._lock:
            row = self._rows.get(schedule_id)
            won = (
                row is not None
                and (row.enabled or self._due_ignores_enabled)
                and row.next_due == due
                and schedule_id not in self._held
            )
            if won:
                self._held[schedule_id] = due
                self.claims_won.append((schedule_id, due))
            else:
                self.claims_lost.append((schedule_id, due))
            return won

    def release(self, schedule_id: str, due: datetime) -> None:
        with self._lock:
            if self._held.get(schedule_id) == due:
                del self._held[schedule_id]
                self.releases.append((schedule_id, due))

    def complete(self, schedule_id: str, due: datetime, *, next_due: datetime, last_world_id: str) -> None:
        with self._lock:
            if self._held.get(schedule_id) != due:
                raise AssertionError(f"complete({schedule_id!r}) without holding the claim for {due.isoformat()}")
            row = self._rows[schedule_id]
            self._rows[schedule_id] = replace(
                row, next_due=next_due, last_slot=slot_key(schedule_id, due), last_world_id=last_world_id
            )
            del self._held[schedule_id]
            self.completions.append((schedule_id, due))


class StartFailed(Exception):
    """What a failing run starter raises (Cloud Tasks unavailable, Firestore contention, ...)."""


class FakeRunStarter:
    """`RunStarter`: records every attempt, allocates world ids, never deduplicates.

    `fail_next(n)` makes the next n attempts raise `StartFailed`. With `gate` set, every attempt blocks
    inside `start` until the gate opens (the concurrency tests hold the race open that way).
    """

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._failures: deque[Exception] = deque()
        self._counter = 0
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.attempts: list[RunStart] = []
        self.started: list[RunStart] = []
        self.world_ids: list[str] = []
        self.clock_at_start: list[datetime | None] = []

    def fail_next(self, n: int = 1, exc: Exception | None = None) -> None:
        with self._lock:
            self._failures.extend(exc or StartFailed("starter unavailable") for _ in range(n))

    def clear_failures(self) -> None:
        with self._lock:
            self._failures.clear()

    def start(self, run: RunStart) -> str:
        with self._lock:
            self.attempts.append(run)
            failure = self._failures.popleft() if self._failures else None
        self.entered.set()
        if self.gate is not None and not self.gate.wait(timeout=10):
            raise AssertionError("test gate never opened")
        if failure is not None:
            raise failure
        with self._lock:
            self._counter += 1
            world_id = f"w_sched_{self._counter:03d}"
            self.started.append(run)
            self.world_ids.append(world_id)
            self.clock_at_start.append(self._clock() if self._clock else None)
        return world_id


class FakeFlags:
    """`FlagStore` (the Protocol of tilo_metering.flags): unset flags read False."""

    def __init__(self) -> None:
        self._values: dict[str, bool] = {}
        self.reads: list[str] = []

    def get(self, name: str) -> bool:
        self.reads.append(name)
        return self._values.get(name, False)

    def set(self, name: str, value: bool, *, reason: str) -> None:
        if not isinstance(value, bool):
            raise TypeError("flags take a bool")
        self._values[name] = value

    def history(self, name: str) -> tuple[Any, ...]:
        return ()


class AlertLog:
    """The `alerts` sink of `Ticker`: `(world_id, emit_kwargs)` per call."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, world_id: str, kwargs: dict[str, Any]) -> None:
        with self._lock:
            self.calls.append((world_id, kwargs))


@dataclass
class Rig:
    ticker: Ticker
    store: MemoryScheduleStore
    starter: FakeRunStarter
    flags: FakeFlags
    clock: Clock
    alerts: AlertLog


def make_rig(
    schedules: Iterable[Schedule] | None = None,
    *,
    now: datetime = MON_0330Z,
    starter: FakeRunStarter | None = None,
    store: MemoryScheduleStore | None = None,
    clock: Clock | None = None,
) -> Rig:
    clock = clock if clock is not None else Clock(now)
    the_store = (
        store if store is not None else MemoryScheduleStore([make_schedule()] if schedules is None else schedules)
    )
    the_starter = starter if starter is not None else FakeRunStarter(clock)
    flags = FakeFlags()
    alerts = AlertLog()
    ticker = Ticker(store=the_store, starter=the_starter, flags=flags, clock=clock, alerts=alerts)
    return Rig(ticker, the_store, the_starter, flags, clock, alerts)


# ---------------------------------------------------------------------------
# OIDC verifier fake (same Protocol as tilo_channels.gmail_watch.OidcVerifier)


class FakeOidcVerifier:
    """`verify(token, audience) -> claims`: knows only the tokens a test registered; anything else raises,
    as google-auth does for a bad signature, expiry or audience."""

    def __init__(self) -> None:
        self._claims: dict[str, Mapping[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []

    def register(
        self,
        email: str | None,
        *,
        aud: str = AUDIENCE,
        email_verified: bool = True,
        iss: str = GOOGLE_ISSUER,
    ) -> str:
        token = "tok-" + secrets.token_urlsafe(24)  # assembled at runtime, never a real credential
        claims: dict[str, Any] = {"aud": aud, "iss": iss, "email_verified": email_verified}
        if email is not None:
            claims["email"] = email
        self._claims[token] = claims
        return token

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        self.calls.append((token, audience))
        if token not in self._claims:
            raise ValueError("token not accepted")
        return self._claims[token]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
