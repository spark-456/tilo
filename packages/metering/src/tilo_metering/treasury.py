"""Treasury (PRD 14.1, 14.5, FR-MTR-02, FR-MTR-04): reserve estimate+15% before a step, commit the
actual after, append-only ledger. Daily USD spend caps, alerts and kill-switch flipping are P8-01c."""

import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import uuid4

from .config import MeteringConfig
from .errors import number
from .flags import FlagStore
from .prices import PriceBook, Usage

_EPS = 1e-9
_Bucket = tuple[object, ...]  # ("run", run_id) | ("user", user_id, day) | ("org", org_id, day)


@dataclass(frozen=True)
class Reservation:
    id: str
    run_id: str
    step_id: str
    amount: float


@dataclass(frozen=True)
class Wait:
    reason: str


@dataclass(frozen=True)
class CommitResult:
    overrun: bool


@dataclass(frozen=True)
class RunBudget:
    run_id: str
    cap: float
    spent: float
    reserved: float
    remaining: float
    halted: bool


@dataclass(frozen=True)
class LedgerEntry:
    kind: str  # reserve | commit | release | grant | usage
    run: str
    user: str
    org: str
    step: str | None
    credits: float | None
    usage: Usage | None
    price_effective_date: str | None
    price_source: str | None
    at: datetime


@dataclass
class _Run:
    cap: float
    user_id: str
    org_id: str
    halted: bool = False


@dataclass(frozen=True)
class _Active:
    run_id: str
    step_id: str
    amount: float
    user_id: str
    org_id: str
    day: date


def _amount(value: object, name: str) -> float:
    v = number(value)
    if v < 0:
        raise ValueError(f"{name} must be >= 0, got {v}")
    return v


def _ident(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value


def _aware(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"at must be a timezone-aware datetime, got {value!r}")
    return value


class Treasury:
    """Thread-safe. `run(id)` and `.ledger` read the same state `reserve`/`commit`/... mutate."""

    def __init__(self, config: MeteringConfig, prices: PriceBook, flags: FlagStore) -> None:
        self._config, self._prices, self._flags = config, prices, flags
        self._lock = threading.Lock()
        self._runs: dict[str, _Run] = {}
        self._reserved: dict[_Bucket, float] = defaultdict(float)
        self._committed: dict[_Bucket, float] = defaultdict(float)
        self._active: dict[str, _Active] = {}
        self._ledger: list[LedgerEntry] = []

    def open_run(self, run_id: str, *, user_id: str, org_id: str, approved: float) -> RunBudget:
        run_id, user_id, org_id = _ident(run_id, "run_id"), _ident(user_id, "user_id"), _ident(org_id, "org_id")
        approved = _amount(approved, "approved")
        with self._lock:
            if run_id in self._runs:
                raise ValueError(f"run {run_id!r} is already open")
            run_cap = self._config.caps.run_credits
            cap = min(approved, run_cap) if run_cap is not None else approved
            self._runs[run_id] = _Run(cap=cap, user_id=user_id, org_id=org_id)
        return self.run(run_id)

    def reserve(self, run_id: str, step_id: str, estimate: float, *, at: datetime) -> Reservation | Wait:
        run_id, step_id = _ident(run_id, "run_id"), _ident(step_id, "step_id")
        estimate, at = _amount(estimate, "estimate"), _aware(at)
        amount = estimate * (1 + self._config.treasury.reserve_margin)
        day = at.date()
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise ValueError(f"run {run_id!r} is not open")
            if self._flags.get("replay_only"):
                return Wait("replay_only")
            if run.halted:
                return Wait("halted")
            caps = self._config.caps
            checks: list[tuple[str, _Bucket, float]] = [("run_cap", ("run", run_id), run.cap)]
            if caps.user_day_credits is not None:
                checks.append(("user_day_cap", ("user", run.user_id, day), caps.user_day_credits))
            if caps.org_day_credits is not None:
                checks.append(("org_day_cap", ("org", run.org_id, day), caps.org_day_credits))
            for reason, bucket, cap in checks:
                if self._committed[bucket] + self._reserved[bucket] + amount > cap + _EPS:
                    return Wait(reason)
            res_id = uuid4().hex
            for _, bucket, _ in checks:
                self._reserved[bucket] += amount
            self._active[res_id] = _Active(run_id, step_id, amount, run.user_id, run.org_id, day)
            self._append("reserve", run_id, run.user_id, run.org_id, step_id, amount, None, None, None, at)
        return Reservation(res_id, run_id, step_id, amount)

    def commit(
        self, reservation: Reservation, actual: float, *, at: datetime, usage: Usage | None = None
    ) -> CommitResult:
        actual, at = _amount(actual, "actual"), _aware(at)
        price_date = price_source = None
        if usage is not None:
            quote = self._prices.quote(usage.profile, at)
            price_date, price_source = quote.effective_date, quote.source
        return self._commit(reservation, actual, at, usage, price_date, price_source)

    def commit_usage(self, reservation: Reservation, usage: Usage, *, at: datetime) -> CommitResult:
        at = _aware(at)
        quote = self._prices.quote(usage.profile, at)  # UnpricedError leaves the reservation untouched
        actual = self._prices.credits(usage, at)
        return self._commit(reservation, actual, at, usage, quote.effective_date, quote.source)

    def _commit(self, reservation, actual, at, usage, price_date, price_source) -> CommitResult:
        with self._lock:
            active = self._active.pop(reservation.id, None)
            if active is None:
                raise ValueError(f"unknown or already-resolved reservation {reservation.id!r}")
            for bucket in (
                ("run", active.run_id),
                ("user", active.user_id, active.day),
                ("org", active.org_id, active.day),
            ):
                self._reserved[bucket] -= active.amount
            day = at.date()
            for bucket in (("run", active.run_id), ("user", active.user_id, day), ("org", active.org_id, day)):
                self._committed[bucket] += actual
            self._append(
                "commit",
                active.run_id,
                active.user_id,
                active.org_id,
                active.step_id,
                actual,
                usage,
                price_date,
                price_source,
                at,
            )
            run = self._runs[active.run_id]
            overrun = self._committed[("run", active.run_id)] > run.cap + _EPS
            run.halted = run.halted or overrun
        return CommitResult(overrun=overrun)

    def release(self, reservation: Reservation) -> None:
        with self._lock:
            active = self._active.pop(reservation.id, None)
            if active is None:
                raise ValueError(f"unknown or already-resolved reservation {reservation.id!r}")
            for bucket in (
                ("run", active.run_id),
                ("user", active.user_id, active.day),
                ("org", active.org_id, active.day),
            ):
                self._reserved[bucket] -= active.amount
            self._append(
                "release",
                active.run_id,
                active.user_id,
                active.org_id,
                active.step_id,
                None,
                None,
                None,
                None,
                datetime.now(tz=UTC),
            )

    def grant(self, run_id: str, credits: float) -> None:
        run_id, amount = _ident(run_id, "run_id"), _amount(credits, "credits")
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise ValueError(f"run {run_id!r} is not open")
            run.cap += amount
            self._append("grant", run_id, run.user_id, run.org_id, None, amount, None, None, None, datetime.now(tz=UTC))

    def record_usage(self, run_id: str, usage: Usage, *, at: datetime) -> None:
        """Meters recorded usage only: always works, even with unset prices; credits stays None."""
        run_id, at = _ident(run_id, "run_id"), _aware(at)
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise ValueError(f"run {run_id!r} is not open")
            self._append("usage", run_id, run.user_id, run.org_id, None, None, usage, None, None, at)

    def run(self, run_id: str) -> RunBudget:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise ValueError(f"run {run_id!r} is not open")
            spent, reserved = self._committed[("run", run_id)], self._reserved[("run", run_id)]
        return RunBudget(run_id, run.cap, spent, reserved, run.cap - spent - reserved, run.halted)

    @property
    def ledger(self) -> tuple[LedgerEntry, ...]:
        with self._lock:
            return tuple(self._ledger)

    def _append(self, kind, run, user, org, step, credits, usage, price_date, price_source, at) -> None:
        self._ledger.append(LedgerEntry(kind, run, user, org, step, credits, usage, price_date, price_source, at))
