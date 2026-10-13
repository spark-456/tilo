"""SEC-16 and FR-MTR-04: live-model spend caps, the per-uid rate limit and the durable replay-only switch
(tests/API_SEC_16.md). Deterministic code; a model never decides who may spend. Money is an `int` in INR minor units,
never a float; every cap comes from `config/spend_caps.yaml`. `SpendGuard` never raises: any doubt means replay."""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import yaml
from tilo_metering.flags import Change, FlagStore

logger = logging.getLogger("tilo_api.spend")
_CONFIG = Path(__file__).resolve().parents[4] / "config" / "spend_caps.yaml"
CAP_REACHED = "You have reached the lifetime spending cap for live models, so new work is refused for now."


class SpendConfigError(ValueError):
    """`config/spend_caps.yaml` is unusable: nothing is defaulted, so no cap is ever silently lifted."""


class SpendCapReached(Exception):
    """New live work for a uid at its lifetime cap: tilo_api.app answers 403 `spend_cap_reached`."""


def _int(value: object, name: str, minimum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer (minor units for money)")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


@dataclass(frozen=True, kw_only=True)
class SpendCaps:
    uid_lifetime_minor: int
    run_minor: int
    org_day_minor: int | None  # None: no per-org daily cap (ADR-0002 decision 13)
    global_day_hard_minor: int
    unit_reserve_minor: int  # BQ-SEC16-1: reserved and settled per live unit until PL-06 prices exist
    rate_limit_requests: int
    rate_limit_window_s: int

    def __post_init__(self) -> None:
        for f in fields(self):
            if not (f.name == "org_day_minor" and self.org_day_minor is None):
                _int(getattr(self, f.name), f.name, 1)


def load_spend_caps(path: str | Path | None = None) -> SpendCaps:
    """Every key required and no other (`contracts/spend_caps.schema.json`); a missing file raises."""
    try:
        doc = yaml.safe_load(Path(path if path is not None else _CONFIG).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpendConfigError("spend_caps.yaml is not plain YAML") from exc
    expected = {f.name for f in fields(SpendCaps)} | {"currency"}
    if not isinstance(doc, dict) or set(doc) != expected or doc["currency"] != "INR":
        raise SpendConfigError(f"spend_caps.yaml must be a mapping of exactly {sorted(expected)}, currency INR")
    try:
        return SpendCaps(**{k: v for k, v in doc.items() if k != "currency"})
    except (TypeError, ValueError) as exc:
        raise SpendConfigError(f"spend_caps.yaml: {exc}") from exc


@dataclass(frozen=True)
class Reservation:
    id: str
    uid: str
    run_id: str
    org_id: str
    amount_minor: int


@dataclass(frozen=True)
class Refused:
    reason: str  # uid_lifetime, run, org_day, global_hard or replay_only


@dataclass(frozen=True)
class Settled:
    overrun: bool  # the actual was above its reservation; recorded in full all the same (MT-03)


class SpendLedger(Protocol):
    def reserve(
        self, *, uid: str, run_id: str, org_id: str, amount_minor: int, at: datetime
    ) -> Reservation | Refused: ...
    def settle(self, reservation: Reservation, actual_minor: int) -> Settled: ...
    def release(self, reservation: Reservation) -> None: ...
    def spent_minor(self, uid: str) -> int: ...
    def settled_minor(self, uid: str) -> int: ...
    def replay_only(self) -> bool: ...
    def trip_replay_only(self, reason: str) -> bool: ...
    def reset_replay_only(self, *, by: str) -> None: ...


class InMemorySpendLedger:
    """`shared` is the whole state: two ledgers over one dict are one store (a restart). A Firestore ledger replaces
    this class and must do each of reserve, settle and the trip as one transaction."""

    def __init__(self, caps: SpendCaps, *, shared: dict[str, Any] | None = None) -> None:
        s = shared if shared is not None else {}
        self._caps, self._lock = caps, s.setdefault("lock", threading.Lock())
        self._settled: dict[tuple[str, ...], int] = s.setdefault("settled", {})
        self._held: dict[tuple[str, ...], int] = s.setdefault("held", {})
        self._holds: dict[str, tuple[tuple[tuple[str, ...], ...], int]] = s.setdefault("holds", {})
        self._switch: dict[str, Any] = s.setdefault("switch", {"on": False, "log": []})

    def _add(self, totals: dict[tuple[str, ...], int], key: tuple[str, ...], amount: int) -> None:
        totals[key] = totals.get(key, 0) + amount
        if not totals[key]:
            del totals[key]

    def reserve(self, *, uid: str, run_id: str, org_id: str, amount_minor: int, at: datetime) -> Reservation | Refused:
        amount = _int(amount_minor, "amount_minor", 0)
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError("`at` must be a timezone-aware datetime")
        if not all(isinstance(x, str) and x for x in (uid, run_id, org_id)):
            raise ValueError("uid, run_id and org_id must be non-empty strings")
        day, c = at.astimezone(UTC).date().isoformat(), self._caps  # caps per UTC day
        checks = (
            ("uid_lifetime", ("uid", uid), c.uid_lifetime_minor),
            ("run", ("run", run_id), c.run_minor),
            ("org_day", ("org", org_id, day), c.org_day_minor),
            ("global_hard", ("day", day), c.global_day_hard_minor),
        )
        with self._lock:
            if self._switch["on"]:
                return Refused("replay_only")
            for reason, key, cap in checks:  # settled plus outstanding; exactly the cap passes
                if cap is not None and self._settled.get(key, 0) + self._held.get(key, 0) + amount > cap:
                    if reason == "global_hard":
                        self._trip("the daily hard cap would be exceeded")
                    return Refused(reason)
            rid, keys = uuid.uuid4().hex, tuple(key for _, key, _ in checks)
            for key in keys:
                self._add(self._held, key, amount)
            self._holds[rid] = (keys, amount)
        return Reservation(id=rid, uid=uid, run_id=run_id, org_id=org_id, amount_minor=amount)

    def settle(self, reservation: Reservation, actual_minor: int) -> Settled:
        actual = _int(actual_minor, "actual_minor", 0)  # a bad actual leaves the hold in place
        with self._lock:
            keys, amount = self._holds.pop(reservation.id)  # KeyError: settled or released already
            for key in keys:
                self._add(self._held, key, -amount)
                self._add(self._settled, key, actual)
            if self._settled.get(keys[-1], 0) >= self._caps.global_day_hard_minor:
                self._trip("the daily hard cap was reached")
        return Settled(overrun=actual > amount)

    def release(self, reservation: Reservation) -> None:
        with self._lock:
            keys, amount = self._holds.pop(reservation.id)
            for key in keys:
                self._add(self._held, key, -amount)

    def spent_minor(self, uid: str) -> int:
        with self._lock:
            return self._settled.get(("uid", uid), 0) + self._held.get(("uid", uid), 0)

    def settled_minor(self, uid: str) -> int:
        with self._lock:
            return self._settled.get(("uid", uid), 0)

    def replay_only(self) -> bool:
        with self._lock:
            return bool(self._switch["on"])

    def _trip(self, reason: str) -> bool:
        flipped, self._switch["on"] = not self._switch["on"], True
        if flipped:
            self._switch["log"].append(("tripped", str(reason)))
        return flipped

    def trip_replay_only(self, reason: str) -> bool:
        with self._lock:
            return self._trip(reason)

    def reset_replay_only(self, *, by: str) -> None:
        """The only way back: a named human (no route and no guard reaches it)."""
        if not isinstance(by, str) or not by.strip():
            raise ValueError("a reset names who did it")
        with self._lock:
            self._switch["on"] = False
            self._switch["log"].append(("reset", by))


@dataclass(frozen=True)
class RateDecision:
    allowed: bool
    retry_after_s: int  # whole seconds, 1..window when denied; 0 when allowed


class RateLimiter:
    """Sliding window per key, the key being exactly the uid given. A denied check is not recorded."""

    def __init__(self, *, limit: int, window_s: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit, self._window = _int(limit, "limit", 1), _int(window_s, "window_s", 1)
        self._clock, self._hits, self._lock = clock, dict[str, deque[float]](), threading.Lock()

    def check(self, uid: str) -> RateDecision:
        with self._lock:
            now, hits = self._clock(), self._hits.setdefault(uid, deque())
            while hits and hits[0] <= now - self._window:
                hits.popleft()
            if len(hits) < self._limit:
                hits.append(now)
                return RateDecision(True, 0)
            wait = math.ceil(hits[0] + self._window - now)
        return RateDecision(False, min(self._window, max(1, wait)))


@dataclass(frozen=True)
class UnitPlan:
    mode: Literal["live", "replay"]
    reservation: Reservation | None
    reason: str | None


class SpendGuard:
    """Between a unit and the ledger, asked before every unit. Never raises; it has no way to clear the switch."""

    def __init__(self, ledger: SpendLedger, flags: FlagStore, caps: SpendCaps) -> None:
        self._ledger, self._flags, self._caps = ledger, flags, caps

    def _switch(self) -> bool:  # raises on a store error
        return bool(self._flags.get("replay_only")) or bool(self._ledger.replay_only())

    def begin_unit(
        self, mode: str, *, uid: str, run_id: str, org_id: str, estimate_minor: int, at: datetime
    ) -> UnitPlan:
        if mode != "live":
            return UnitPlan("replay", None, None)
        try:
            if self._switch():
                return UnitPlan("replay", None, "replay_only")
            estimate = _int(estimate_minor, "estimate_minor", 0)
            result = self._ledger.reserve(uid=uid, run_id=run_id, org_id=org_id, amount_minor=estimate, at=at)
        except Exception as exc:
            logger.warning("live denied, the spend check failed: %s", type(exc).__name__)
            return UnitPlan("replay", None, "unavailable")
        if (reason := getattr(result, "reason", None)) is not None:
            return UnitPlan("replay", None, str(reason))
        return UnitPlan("live", cast(Reservation, result), None)

    def settle_unit(self, plan: UnitPlan, actual_minor: int) -> None:
        self._close(plan, lambda r: self._ledger.settle(r, actual_minor))

    def abort_unit(self, plan: UnitPlan) -> None:
        self._close(plan, self._ledger.release)

    def _close(self, plan: UnitPlan, close: Callable[[Reservation], object]) -> None:
        if plan.reservation is not None:  # on a failure the hold stays counted: it can only under-spend
            _quiet(lambda: close(cast(Reservation, plan.reservation)))

    def uid_capped(self, uid: str) -> bool:  # unknown is not capped; live_allowed still says no
        return _quiet(lambda: self._ledger.spent_minor(uid) >= self._caps.uid_lifetime_minor)

    def live_allowed(self, uid: str) -> bool:
        return _quiet(lambda: not self._switch() and self._ledger.spent_minor(uid) < self._caps.uid_lifetime_minor)

    def replay_only(self) -> bool:
        return _quiet(self._switch)

    def headroom_minor(self, uid: str) -> int:
        """What the uid may still spend under its (team-lowered) lifetime cap; 0 when it cannot be read."""
        try:
            return max(0, self._caps.uid_lifetime_minor - self._ledger.spent_minor(uid))
        except Exception as exc:
            logger.warning("a spend store is unreachable: %s", type(exc).__name__)
            return 0


def _quiet(read: Callable[[], object]) -> bool:
    """The answer, or False when a store cannot be reached (logged by error type only)."""
    try:
        return bool(read())
    except Exception as exc:
        logger.warning("a spend store is unreachable: %s", type(exc).__name__)
        return False


class Switches:
    """Deployed, the flag store the routes read: NFR-24's flags or the ledger's durable record (None when unwired)
    means `replay_only`. A read never raises: unreachable reads as not set, and the guard then denies live."""

    def __init__(self, flags: FlagStore, ledger: SpendLedger | None) -> None:
        self.flags, self.ledger = flags, ledger

    def get(self, name: str) -> bool:
        ledger = self.ledger if name == "replay_only" else None
        return _quiet(lambda: self.flags.get(name)) or (ledger is not None and _quiet(ledger.replay_only))

    def set(self, name: str, value: bool, *, reason: str) -> None:
        self.flags.set(name, value, reason=reason)

    def history(self, name: str) -> tuple[Change, ...]:
        return self.flags.history(name)
