"""Treasury (PRD 14.1, 14.5, FR-MTR-02, FR-MTR-04): reserve estimate+15% before a step, commit the
actual after, append-only ledger. Commits count on their reservation's UTC day.

Daily USD spend caps (P8-01c, NFR-24): the soft cap raises one Alert per UTC day; the hard cap raises
one Alert, freezes new reserves via the replay_only kill switch, and is also checked pre-emptively in
reserve() so a single large reservation cannot itself push the day over the top."""

import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from .config import MeteringConfig
from .errors import number
from .flags import FlagStore
from .prices import PriceBook, Usage

if TYPE_CHECKING:
    from .cost_alerts import CostAlerts

_EPS = 1e-9


@dataclass(frozen=True)
class Reservation:
    id: str
    run_id: str
    step_id: str
    amount: float
    user: str
    org: str
    day: date


@dataclass(frozen=True)
class Wait:
    reason: str


@dataclass(frozen=True)
class Alert:
    """The first time a UTC day's committed spend reaches a spend threshold (PRD 14.1, NFR-24)."""

    kind: str  # daily_spend_soft | daily_spend_hard
    day: date
    spent_usd: float
    threshold_usd: float


@dataclass(frozen=True)
class CommitResult:
    overrun: bool
    alerts: tuple[Alert, ...] = ()


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
    at: datetime
    step: str | None = None
    credits: float | None = None
    usage: Usage | None = None
    price_effective_date: str | None = None
    price_source: str | None = None
    day: date | None = None  # commit: the reservation's UTC day


@dataclass
class _Run:
    cap: float
    user_id: str
    org_id: str
    halted: bool = False


def _amount(value: object, name: str) -> float:
    v = number(value)
    if v < 0:
        raise ValueError(f"{name} must be >= 0, got {v}")
    return v


def _aware(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"at must be a timezone-aware datetime, got {value!r}")
    return value


class Treasury:
    """Thread-safe. Totals are summed from the ledger and the outstanding reservations, not cached."""

    def __init__(
        self, config: MeteringConfig, prices: PriceBook, flags: FlagStore, cost_alerts: "CostAlerts | None" = None
    ) -> None:
        self._config, self._prices, self._flags = config, prices, flags
        self._cost_alerts = cost_alerts  # NFR-27: alert-only owner alerts, checked after each commit
        self._lock = threading.Lock()
        self._runs: dict[str, _Run] = {}
        self._active: dict[str, Reservation] = {}
        self._ledger: list[LedgerEntry] = []
        self._alerted: dict[date, set[str]] = {}  # UTC day -> spend-alert kinds already raised

    def open_run(self, run_id: str, *, user_id: str, org_id: str, approved: float) -> RunBudget:
        approved = _amount(approved, "approved")
        with self._lock:
            if run_id in self._runs:
                raise ValueError(f"run {run_id!r} is already open")
            run_cap = self._config.caps.run_credits
            cap = min(approved, run_cap) if run_cap is not None else approved
            self._runs[run_id] = _Run(cap, user_id, org_id)
        return self.run(run_id)

    def reserve(self, run_id: str, step_id: str, estimate: float, *, at: datetime) -> Reservation | Wait:
        amount = _amount(estimate, "estimate") * (1 + self._config.treasury.reserve_margin)
        day = _aware(at).astimezone(UTC).date()
        with self._lock:
            run = self._runs[run_id]  # KeyError if the run was never opened
            if self._flags.get("replay_only"):
                return Wait("replay_only")
            if run.halted:
                return Wait("halted")
            if self._committed_run(run_id) + self._reserved_run(run_id) + amount > run.cap + _EPS:
                return Wait("run_cap")
            caps = self._config.caps
            for reason, field, ident, cap in (
                ("user_day_cap", "user", run.user_id, caps.user_day_credits),
                ("org_day_cap", "org", run.org_id, caps.org_day_credits),
            ):
                if cap is not None and self._day_total(field, ident, day) + amount > cap + _EPS:
                    return Wait(reason)
            hard = self._config.spend.daily_usd_hard
            if (self._day_deployment_total(day) + amount) * self._prices.credit_usd > hard + _EPS:
                self._flags.set(
                    "replay_only", True, reason=f"a reservation would cross the ${hard} daily hard spend cap on {day}"
                )
                return Wait("daily_spend_hard")
            reservation = Reservation(uuid4().hex, run_id, step_id, amount, run.user_id, run.org_id, day)
            self._active[reservation.id] = reservation
            self._ledger.append(LedgerEntry("reserve", run_id, run.user_id, run.org_id, at, step_id, amount))
        return reservation

    def commit(
        self, reservation: Reservation, actual: float, *, at: datetime, usage: Usage | None = None
    ) -> CommitResult:
        price_date = price_source = None
        if usage is not None:
            quote = self._prices.quote(usage.profile, at)
            price_date, price_source = quote.effective_date, quote.source
        return self._commit(reservation, _amount(actual, "actual"), _aware(at), usage, price_date, price_source)

    def commit_usage(self, reservation: Reservation, usage: Usage, *, at: datetime) -> CommitResult:
        at = _aware(at)
        quote = self._prices.quote(usage.profile, at)  # UnpricedError leaves the reservation untouched
        actual = self._prices.credits(usage, at)
        return self._commit(reservation, actual, at, usage, quote.effective_date, quote.source)

    def _commit(self, reservation, actual, at, usage, price_date, price_source) -> CommitResult:
        # actual is recorded in full; overrun = actual > the reservation, and it halts the run
        with self._lock:
            active = self._active.pop(reservation.id)  # KeyError if already committed or released
            fields = dict(usage=usage, price_effective_date=price_date, price_source=price_source, day=active.day)
            entry = LedgerEntry("commit", active.run_id, active.user, active.org, at, active.step_id, actual, **fields)
            self._ledger.append(entry)
            overrun = actual > active.amount + _EPS
            self._runs[active.run_id].halted |= overrun
            alerts = self._spend_alerts(active.day)
            snapshot = tuple(self._ledger) if self._cost_alerts is not None else ()
        if self._cost_alerts is not None:
            try:  # outside the lock (the sink does I/O); alert-only, so it can never fail or block a commit
                self._cost_alerts.check(snapshot)
            except Exception:
                pass
        return CommitResult(overrun=overrun, alerts=alerts)

    def release(self, reservation: Reservation) -> None:
        with self._lock:
            active = self._active.pop(reservation.id)
            now = datetime.now(UTC)
            self._ledger.append(LedgerEntry("release", active.run_id, active.user, active.org, now, active.step_id))

    def grant(self, run_id: str, credits: float) -> None:
        amount = _amount(credits, "credits")
        with self._lock:
            run = self._runs[run_id]
            run.cap += amount
            now = datetime.now(UTC)
            self._ledger.append(LedgerEntry("grant", run_id, run.user_id, run.org_id, now, credits=amount))

    def record_usage(self, run_id: str, usage: Usage, *, at: datetime) -> None:
        """Meters recorded usage only: always works, even with unset prices; credits stays None."""
        at = _aware(at)
        with self._lock:
            run = self._runs[run_id]
            self._ledger.append(LedgerEntry("usage", run_id, run.user_id, run.org_id, at, usage=usage))

    def run(self, run_id: str) -> RunBudget:
        with self._lock:
            run = self._runs[run_id]
            spent, reserved = self._committed_run(run_id), self._reserved_run(run_id)
        return RunBudget(run_id, run.cap, spent, reserved, run.cap - spent - reserved, run.halted)

    @property
    def ledger(self) -> tuple[LedgerEntry, ...]:
        with self._lock:
            return tuple(self._ledger)

    def _committed_run(self, run_id: str) -> float:
        return sum(e.credits for e in self._ledger if e.kind == "commit" and e.run == run_id and e.credits is not None)

    def _reserved_run(self, run_id: str) -> float:
        return sum(a.amount for a in self._active.values() if a.run_id == run_id)

    def _day_total(self, field: str, value: str, day: date) -> float:
        """Committed plus outstanding credits of that user or org on that UTC day (the reservation's day)."""
        rows: list[tuple[LedgerEntry | Reservation, float]] = [(a, a.amount) for a in self._active.values()]
        rows += [(e, e.credits or 0.0) for e in self._ledger if e.kind == "commit"]
        return sum(n for r, n in rows if r.day == day and getattr(r, field) == value)

    def _day_committed_total(self, day: date) -> float:
        """Committed credits across every run, user and org on that UTC day."""
        return sum(e.credits or 0.0 for e in self._ledger if e.kind == "commit" and e.day == day)

    def _day_deployment_total(self, day: date) -> float:
        """Committed plus outstanding credits across every run, user and org on that UTC day."""
        return self._day_committed_total(day) + sum(a.amount for a in self._active.values() if a.day == day)

    def _spend_alerts(self, day: date) -> tuple[Alert, ...]:
        """The first time this UTC day's committed USD spend reaches soft, then hard; hard also flips
        replay_only (NFR-24). Must be called with the lock held, after the commit entry is appended."""
        spend, spent_usd = self._config.spend, self._day_committed_total(day) * self._prices.credit_usd
        alerted, raised = self._alerted.setdefault(day, set()), []
        for kind, threshold in (("daily_spend_soft", spend.daily_usd_soft), ("daily_spend_hard", spend.daily_usd_hard)):
            if spent_usd >= threshold - _EPS and kind not in alerted:
                alerted.add(kind)
                raised.append(Alert(kind, day, spent_usd, threshold))
                if kind == "daily_spend_hard":
                    reason = f"daily committed spend ${spent_usd:.2f} reached the ${threshold} hard cap on {day}"
                    self._flags.set("replay_only", True, reason=reason)
        return tuple(raised)
