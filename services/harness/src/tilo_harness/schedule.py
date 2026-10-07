"""Scheduled runs, the "Clock Tower" (FR-AGT-14, PRD 8.6 and 6.3): a weekly schedule fires on time and reuses memory.

One Cloud Scheduler job (`tilo-schedule-tick`, every minute) POSTs `/internal/schedules/tick`; the route calls
`Ticker.tick()`, which reads due schedules from a `ScheduleStore` and starts each through a `RunStarter`. Only ports and
pure logic live here: the Firestore store and the Cloud Tasks starter are wired by a later ticket, so the route answers
503 until then (docs/open-questions.md, the FR-AGT-14 row).

Rules the code keeps:
- Exactly once per slot: the slot is claimed (compare-and-set on `next_due`, held as a lease) BEFORE the run starts; the
  idempotency key of the start is `slot_key`. A start that raises releases the claim and leaves `next_due` alone, so the
  next tick retries the same slot. Only `complete` moves `next_due`.
- On time, never early: a slot is started in the first tick at or after its instant, never before. Missed slots collapse
  into one firing for the latest missed slot plus one info `alert.raised`, never a backfill storm.
- Fails closed: `replay_only` starts nothing and moves nothing; a store or flag read that raises fires nothing that is
  not proven safe (the exception propagates, the route answers 500).
- A scheduled run is the owner's: `world.requested` carries the owner as actor and channel `schedule`, which is never an
  owner instruction (OB-01) and never an approval, so every T3 step still waits for a person.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from tilo_harness.writer import new_ulid

log = logging.getLogger(__name__)

MAX_FIRES_PER_TICK = 20  # PRD 6.3 "start runs with rate limits": the rest stay due and fire on the next tick
CLAIM_LEASE = timedelta(minutes=5)  # a claim held by a crashed instance expires after this (store side)
WEEK = timedelta(days=7)
_MAX_TITLE = 140  # world.requested title and every event summary


@lru_cache(maxsize=64)
def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except Exception as exc:  # unknown, empty or malformed names raise several different types
        raise ValueError(f"unknown IANA time zone {name!r}") from exc


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


@dataclass(frozen=True)
class Cadence:
    """Weekly: the LOCAL weekday (Monday = 0), hour and minute in an IANA zone."""

    weekday: int
    hour: int
    minute: int
    tz: str

    def __post_init__(self) -> None:
        for label, value, high in (("weekday", self.weekday, 6), ("hour", self.hour, 23), ("minute", self.minute, 59)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high:
                raise ValueError(f"cadence {label} must be an integer 0..{high}")
        if not isinstance(self.tz, str) or not self.tz:
            raise ValueError("cadence tz must be an IANA zone name")
        _zone(self.tz)


def _gap_end(zone: ZoneInfo, naive: datetime) -> datetime:
    """The first instant after the transition that swallowed the non-existent wall time `naive`."""
    before = zone.utcoffset(naive.replace(fold=0))
    after = zone.utcoffset(naive.replace(fold=1))
    assert before is not None and after is not None
    lo = (naive - after).replace(tzinfo=UTC)  # still before the transition
    hi = (naive - before).replace(tzinfo=UTC)  # already after it
    while hi - lo > timedelta(seconds=1):
        mid = lo + (hi - lo) // 2
        mid = mid.replace(microsecond=0)
        if mid.astimezone(zone).utcoffset() == after:
            hi = mid
        else:
            lo = mid
    return hi


def _slot_on(cadence: Cadence, day: date) -> datetime:
    """The cadence's instant on one local calendar day, in UTC. A wall time that does not exist (DST gap) fires at
    the end of the gap; an ambiguous one (DST overlap) fires at its first occurrence."""
    zone = _zone(cadence.tz)
    naive = datetime(day.year, day.month, day.day, cadence.hour, cadence.minute)
    instant = naive.replace(tzinfo=zone, fold=0).astimezone(UTC)
    if instant.astimezone(zone).replace(tzinfo=None) != naive:  # round trip moved: the wall time is in a gap
        return _gap_end(zone, naive)
    return instant


def next_slot(cadence: Cadence, after: datetime) -> datetime:
    """The first slot STRICTLY after `after`, UTC-aware. Pure; local wall time is kept across DST."""
    _aware(after, "after")
    first = after.astimezone(_zone(cadence.tz)).date() - timedelta(days=1)
    for offset in range(10):
        day = first + timedelta(days=offset)
        if day.weekday() == cadence.weekday:
            slot = _slot_on(cadence, day)
            if slot > after:
                return slot
    raise AssertionError("a weekly cadence always has a slot within ten days")  # pragma: no cover


def _latest_slot(cadence: Cadence, next_due: datetime, now: datetime) -> tuple[datetime, int]:
    """(latest slot <= now, slots skipped before it) for `next_due <= now`, by arithmetic over whole weeks and then a
    few next_slot steps, so a year-old due time costs the same as a minute-old one."""
    cur, skipped = next_due, 0
    zone = _zone(cadence.tz)
    if (now - cur) // WEEK > 2 and cur.astimezone(zone).weekday() != cadence.weekday:
        cur, skipped = next_slot(cadence, cur), 1  # a misaligned `next_due`: land on a slot first, then jump
    weeks = (now - cur) // WEEK - 2
    if weeks > 0:
        cur, skipped = _slot_on(cadence, cur.astimezone(zone).date() + timedelta(weeks=weeks)), skipped + weeks
    while (following := next_slot(cadence, cur)) <= now:
        cur, skipped = following, skipped + 1
    return cur, skipped


@dataclass(frozen=True, kw_only=True)
class Schedule:
    """Firestore `schedules/{schedule_id}` in production; a store-side record, not a contract."""

    schedule_id: str
    owner_user_id: str
    title: str
    cadence: Cadence
    approved_brief_ref: str  # world id of the run the owner approved
    budget_cap: float
    enabled: bool = True
    next_due: datetime
    last_slot: str | None = None
    last_world_id: str | None = None
    # FR-AGT-14b: the owner's approved brief and approach are SNAPSHOTTED here (a task may not survive a redeploy)
    brief: dict[str, Any] | None = None
    approach: dict[str, Any] | None = None
    failures: int = 0
    backoff_until: datetime | None = None
    last_error: str | None = None  # a short fixed code (^[a-z][a-z0-9_]{0,63}$), never exception text
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        _aware(self.next_due, "next_due")
        for label, value in (("backoff_until", self.backoff_until), ("created_at", self.created_at)):
            if value is not None:
                _aware(value, label)
        if (
            isinstance(self.budget_cap, bool)
            or not isinstance(self.budget_cap, int | float)
            or not 0 < self.budget_cap < float("inf")
        ):
            raise ValueError("budget_cap must be a finite number above 0")  # NaN fails the comparison too


def slot_key(schedule_id: str, due: datetime) -> str:
    """`<schedule_id>:<due as UTC ISO-8601>`: a pure function of (schedule, instant), the idempotency key of a start."""
    _aware(due, "due")
    return f"{schedule_id}:{due.astimezone(UTC).isoformat()}"


def task_name(key: str) -> str:
    """A stable Cloud Tasks task name for a slot key (names allow only [A-Za-z0-9_-]); the raw key stays the key."""
    return "sched-" + hashlib.sha256(key.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RunStart:
    idempotency_key: str  # == slot_key(schedule_id, slot); identical on every retry of the same slot
    schedule_id: str
    owner_user_id: str
    title: str
    approved_brief_ref: str
    prior_world_id: str | None  # the schedule's last_world_id: artifact memory offered, never silently reused
    budget_cap: float
    slot: datetime  # the slot being fired (UTC): the LATEST missed one when several were missed
    skipped: int  # missed slots collapsed into this firing
    cache_namespace: str  # == schedule_id: the result cache namespace (web results go stale after 7 days)


class StartSkipped(Exception):
    """A start that deliberately did nothing. `advance`: next_due moves to the first slot after the one skipped (retry
    next week); otherwise the slot stays and is retried after the backoff. `code` is a short fixed code, never text.
    `count=False` is for a condition of the whole service, not of one schedule: the claim is released and NOTHING is
    recorded (no failure, no backoff, no move), whatever `advance` says. `stop` (with `count=False`) also ends the tick:
    no later slot is tried and every one stays due; the tick result names `code` and `status` (HTTP status or None)."""

    def __init__(
        self, code: str, *, advance: bool = False, count: bool = True, stop: bool = False, status: int | None = None
    ) -> None:
        super().__init__(code)
        self.code, self.advance, self.count, self.stop, self.status = code, advance, count, stop, status


GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})  # exact, case-sensitive
START_FAILED = "start_failed"  # the fixed code a raising start is recorded under


def tick_caller_ok(claims: Mapping[str, Any], *, audience: str, caller: str) -> bool:
    """The verified token claims of a tick call: Google issuer, our audience, the one allowed verified account."""
    return (
        isinstance(claims.get("iss"), str)
        and claims["iss"] in GOOGLE_ISSUERS
        and claims.get("aud") == audience
        and claims.get("email") == caller
        and claims.get("email_verified") is True
    )


class ScheduleStore(Protocol):
    """Atomic in production (a Firestore transaction). A claim is a lease of `CLAIM_LEASE`: one held by a crashed
    instance expires and the slot is claimable again."""

    def due(self, now: datetime, limit: int) -> list[Schedule]:
        """Enabled schedules with next_due <= now, oldest next_due first (ties by schedule_id), at most `limit`."""
        ...

    def claim(self, schedule_id: str, due: datetime) -> bool:
        """True iff the schedule is enabled, its next_due == due and no live claim is held; then a claim is held."""
        ...

    def release(self, schedule_id: str, due: datetime) -> None:
        """Drops the claim for `due`; next_due and every other field unchanged."""
        ...

    def complete(self, schedule_id: str, due: datetime, *, next_due: datetime, last_world_id: str) -> None:
        """The only call that moves next_due; sets last_slot = slot_key(schedule_id, due), drops the claim."""
        ...


class RunStarter(Protocol):
    def start(self, run: RunStart) -> str:
        """Returns the new run's world id; raises on failure. Idempotent on `run.idempotency_key`."""
        ...


class FlagReader(Protocol):  # the read side of tilo_metering.flags.FlagStore
    def get(self, name: str) -> bool: ...


class OidcVerifier(Protocol):  # google-auth id_token verification in production
    def verify(self, token: str, audience: str) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class TickResult:
    fired: int
    stopped: str | None = None  # the code of a `StartSkipped(stop=True)` that ended the tick early
    status: int | None = None  # its HTTP status, when the starter knew one


def world_requested_kwargs(run: RunStart, world_id: str) -> dict[str, Any]:
    """`WorldWriter.emit` kwargs for a scheduled run's first event. The actor is the schedule's owner (the world's
    owner is the actor of its first world.requested, OB-01), the channel `schedule`, the destination null."""
    title = (run.title.strip() or "Scheduled run")[:_MAX_TITLE]
    return {
        "type": "world.requested",
        "actor": run.owner_user_id,
        "target": world_id,
        "summary": f"Your schedule started: {title}"[:_MAX_TITLE],
        "data": {"title": title, "channel": "schedule", "destination": None},
    }


def skipped_alert_kwargs(world_id: str, skipped: int, alert_id: str) -> dict[str, Any]:
    """An info `alert.raised`: it tells the owner how many missed runs were collapsed, and asks for nothing."""
    plural = "run was" if skipped == 1 else "runs were"
    return {
        "type": "alert.raised",
        "actor": "system",
        "target": world_id,
        "severity": "info",
        "summary": f"{skipped} missed scheduled {plural} skipped; the latest one started."[:_MAX_TITLE],
        "data": {"alert_id": alert_id, "card_id": None},
    }


class Ticker:
    def __init__(
        self,
        *,
        store: ScheduleStore,
        starter: RunStarter,
        flags: FlagReader,
        clock: Callable[[], datetime],
        alerts: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self._store, self._starter, self._flags, self._clock, self._alerts = store, starter, flags, clock, alerts

    def tick(self) -> TickResult:
        """Starts every schedule due now (at most MAX_FIRES_PER_TICK). A store or flag read that raises propagates:
        nothing is started that was not proven safe. One schedule's failing start never stops the others; only a
        service-wide `StartSkipped(stop=True)` ends the tick."""
        now = self._clock()
        if self._flags.get(
            "replay_only"
        ):  # NFR-24: a replay-only link starts nothing; the slot fires once when cleared
            return TickResult(0)
        fired = 0
        uncounted: set[str] = set()  # fixed codes of uncounted skips, each logged once per tick
        for schedule in self._store.due(now, MAX_FIRES_PER_TICK)[:MAX_FIRES_PER_TICK]:
            if not schedule.enabled or schedule.next_due > now:  # never trust the store with either rule
                continue
            due = schedule.next_due
            if not self._store.claim(schedule.schedule_id, due):
                continue
            # Everything after the claim is inside the try: any exception records a failure and frees the claim.
            slot: datetime | None = None
            try:
                slot, skipped = _latest_slot(schedule.cadence, due, now)
                run = RunStart(
                    idempotency_key=slot_key(schedule.schedule_id, slot),
                    schedule_id=schedule.schedule_id,
                    owner_user_id=schedule.owner_user_id,
                    title=schedule.title,
                    approved_brief_ref=schedule.approved_brief_ref,
                    prior_world_id=schedule.last_world_id,
                    budget_cap=schedule.budget_cap,
                    slot=slot,
                    skipped=skipped,
                    cache_namespace=schedule.schedule_id,
                )
                world_id = self._starter.start(run)
            except StartSkipped as skip:  # a deliberate no-op: recorded, and may give the slot up until next week
                if not skip.count:  # a global condition: nothing is recorded, the slot is claimable on the next tick
                    if skip.code not in uncounted:
                        uncounted.add(skip.code)
                        log.warning("schedule starts skipped, not counted (%s)", skip.code)
                    self._release(schedule.schedule_id, due)
                    if skip.stop:  # no later start can succeed this tick: they all stay due
                        return TickResult(fired, stopped=skip.code, status=skip.status)
                    continue
                log.info("schedule start skipped (%s)", skip.code)
                after = next_slot(schedule.cadence, slot) if skip.advance and slot is not None else None
                self._fail(schedule.schedule_id, due, skip.code, after)
                continue
            except Exception as exc:  # any failure: slot claimable again, next_due unmoved, retried after the backoff
                log.warning("schedule start failed (%s); retrying after the backoff", type(exc).__name__)
                self._fail(schedule.schedule_id, due, START_FAILED, None)
                continue
            # The run started. `complete` failing leaves the claim held (it expires; the same key dedupes a restart);
            # it never aborts the tick for the other schedules.
            assert slot is not None  # the try only reaches here after the slot arithmetic
            fired += 1
            try:
                self._store.complete(
                    schedule.schedule_id, due, next_due=next_slot(schedule.cadence, slot), last_world_id=world_id
                )
            except Exception as exc:
                log.error("schedule complete failed (%s); the claim will lapse", type(exc).__name__)
            if skipped:
                self._alert(world_id, skipped, now)
        return TickResult(fired)

    def _fail(self, schedule_id: str, due: datetime, error: str, next_due: datetime | None) -> None:
        """Records the failure (a store without `record_failure` retries every tick) and frees the claim."""
        record = getattr(self._store, "record_failure", None)
        if record is not None:
            try:
                record(schedule_id, due, error=error, next_due=next_due)
            except Exception as exc:  # the lease expires on its own; the tick goes on
                log.error("schedule failure not recorded (%s)", type(exc).__name__)
        self._release(schedule_id, due)

    def _release(self, schedule_id: str, due: datetime) -> None:
        try:
            self._store.release(schedule_id, due)
        except Exception as exc:  # the lease expires on its own; a failed release must not mask the start failure
            log.warning("schedule release failed (%s); the claim will lapse", type(exc).__name__)

    def _alert(self, world_id: str, skipped: int, now: datetime) -> None:
        try:
            self._alerts(world_id, skipped_alert_kwargs(world_id, skipped, new_ulid(now)))
        except Exception as exc:  # the run already started: an alert failure never undoes or repeats it
            log.warning("skipped-run alert failed (%s)", type(exc).__name__)


@dataclass(frozen=True)
class TickWiring:
    """What the tick route needs. The caller allowlist and the audience come from here, never from the request."""

    verifier: OidcVerifier
    audience: str  # the harness URL: the `aud` the token must carry
    service_account: str  # the one allowed caller: tilo-schedule-scheduler@<project>.iam.gserviceaccount.com
    ticker: Ticker
