"""Helpers for the SEC-16 and FR-MTR-04 acceptance tests (per-uid rate limit, spend caps, durable replay-only;
see API_SEC_16.md).

Named `_sec16_lib` for the same global-bare-module-name reason as `_sec15_lib.py`. Nothing here is business logic:
the accounting under test lives in `tilo_api.spend`, imported lazily so a missing module fails each test, not
collection. The doubles are a spy that wraps whatever ledger the production code provides (it only records calls),
a ledger that is unreachable, a flag store that is unreachable, a fake clock, and a fake price table (integer minor
units, so the cost of a fake call comes from a table in this file and never from a provider or a price page).

No network, no paid call, no secret.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import _sec15_lib
from _clint1_lib import seam

AT = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
NEXT_DAY = datetime(2026, 10, 7, 0, 30, tzinfo=UTC)

JUDGE_A = "u_sec16_judge_a"
JUDGE_B = "u_sec16_judge_b"
ORG = "org_tilo"
OTHER_ORG = "org_other"

# Small caps so a test reaches a boundary in a few calls. Every number here is a test number, not a product default.
DEFAULT_CAPS: dict[str, Any] = {
    "uid_lifetime_minor": 1_000,
    "run_minor": 1_000,  # the API tests put a uid's whole lifetime cap on one prefill run (`spend`)
    "org_day_minor": 5_000,
    "global_day_hard_minor": 20_000,
    "unit_reserve_minor": 100,
    "rate_limit_requests": 3,
    "rate_limit_window_s": 60,
}

WRITES = frozenset({"reserve", "settle", "release", "trip_replay_only", "reset_replay_only"})


def make_caps(**overrides: Any) -> Any:
    from tilo_api.spend import SpendCaps  # noqa: PLC0415

    return SpendCaps(**{**DEFAULT_CAPS, **overrides})


def make_ledger(caps: Any = None, *, shared: dict | None = None, **overrides: Any) -> Any:
    """The production in-memory ledger. `shared` is its whole state: two ledgers over the same dict are the same
    store, which is how a test restarts a process (a Firestore-backed ledger would be the same store again)."""
    from tilo_api.spend import InMemorySpendLedger  # noqa: PLC0415

    return InMemorySpendLedger(caps if caps is not None else make_caps(**overrides), shared=shared)


def make_guard(ledger: Any, flags: Any = None, caps: Any = None, **overrides: Any) -> Any:
    from tilo_api.spend import SpendGuard  # noqa: PLC0415
    from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415

    return SpendGuard(
        ledger,
        flags if flags is not None else InMemoryFlagStore(),
        caps if caps is not None else make_caps(**overrides),
    )


def spend(
    ledger: Any, uid: str, minor: int, *, run_id: str = "r_prefill", org_id: str = ORG, at: datetime = AT
) -> None:
    """Puts `minor` on `uid`'s lifetime total through the public reserve and settle calls (a test must not reach
    into the ledger's state)."""
    held = ledger.reserve(uid=uid, run_id=run_id, org_id=org_id, amount_minor=minor, at=at)
    assert not hasattr(held, "reason"), f"setup: the ledger refused {minor}: {held}"
    ledger.settle(held, minor)


class FakePriceTable:
    """Integer minor units per million tokens, rounded up (never down: a cap is a ceiling). A fake: not a price list."""

    def __init__(self, input_per_m: int = 300, output_per_m: int = 1_200) -> None:
        self.input_per_m, self.output_per_m = input_per_m, output_per_m

    def cost_minor(self, tokens_in: int, tokens_out: int) -> int:
        total = tokens_in * self.input_per_m + tokens_out * self.output_per_m
        return -(-total // 1_000_000)


class FakeClock:
    def __init__(self, start: float = 1_020.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class SpyLedger:
    """Delegates to a real ledger and records every call as (method, kwargs-or-args). `writes` is the subset that
    can change state."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return target(*args, **kwargs)

        return call

    @property
    def writes(self) -> list[str]:
        return [name for name, _, _ in self.calls if name in WRITES]

    @property
    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]


class DeadLedger:
    """A ledger nobody can reach: every call raises (a store outage)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            raise ConnectionError("the spend ledger is unreachable")

        return call


class SettleFailsLedger(SpyLedger):
    """Reserves and reads normally; `settle` and `release` raise (an outage between a unit's start and its end)."""

    def __getattr__(self, name: str) -> Any:
        if name in {"settle", "release"}:

            def boom(*args: Any, **kwargs: Any) -> Any:
                self.calls.append((name, args, kwargs))
                raise ConnectionError("the spend ledger went away")

            return boom
        return super().__getattr__(name)


class DeadFlags:
    """A switch store nobody can reach."""

    def get(self, name: str) -> bool:
        raise ConnectionError("the switch store is unreachable")

    def set(self, name: str, value: bool, *, reason: str) -> None:
        raise ConnectionError("the switch store is unreachable")

    def history(self, name: str) -> tuple:
        raise ConnectionError("the switch store is unreachable")


class SpyLimiter:
    """Wraps a real `RateLimiter` and records the uid of every `check`."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.checked: list[str] = []
        self._lock = threading.Lock()

    def check(self, uid: str) -> Any:
        with self._lock:
            self.checked.append(uid)
        return self._inner.check(uid)


@dataclass
class Sec16:
    """The SEC-15 harness (real app, deployed-style, fake access store, scripted router behind a spy on
    `deps.router_for_mode`) plus the three SEC-16 seams: the spend ledger, the rate limiter and the caps."""

    sec: Any  # _sec15_lib.Sec15
    ledger: Any
    limiter: Any
    caps: Any
    clock: FakeClock
    seen: list[str] = field(default_factory=list)

    # delegate what the SEC-15 harness already does
    def __getattr__(self, name: str) -> Any:
        return getattr(self.sec, name)

    def snapshot(self) -> tuple:
        writes = self.ledger.writes if isinstance(self.ledger, SpyLedger) else []
        return (self.sec.snapshot(), list(writes))


def build(
    monkeypatch: Any,
    *,
    declarations: dict[str, str] | None = None,
    deployed: bool = True,
    judge_live: bool = True,
    ledger: Any = "default",
    flags: Any = None,
    **cap_overrides: Any,
) -> Sec16:
    """`judge_live` sets TILO_JUDGE_LIVE=1, the deployment's permission for judges' live models (SEC-15). `ledger`
    is a ready ledger (a spy over the real one by default); pass `None` to leave the production seam unwired."""
    from tilo_api import app, deps, rate_limit  # noqa: PLC0415
    from tilo_api.spend import RateLimiter  # noqa: PLC0415

    sec = _sec15_lib.build(
        monkeypatch, declarations=declarations or {JUDGE_A: "judge", JUDGE_B: "judge"}, deployed=deployed
    )
    if judge_live:
        monkeypatch.setenv("TILO_JUDGE_LIVE", "1")
    caps = make_caps(**cap_overrides)
    if ledger == "default":
        ledger = SpyLedger(make_ledger(caps))
    clock = FakeClock()
    limiter = SpyLimiter(RateLimiter(limit=caps.rate_limit_requests, window_s=caps.rate_limit_window_s, clock=clock))
    # OLD-4: both installed limiter layers follow the same test clock. Keep the
    # SEC-10 edge limiter and its configured quotas; advancing a SEC-16 window
    # must also refill the edge buckets rather than exhaust a real-time singleton.
    edge_limiter = rate_limit.InMemoryRateLimiter(clock=clock)
    app.dependency_overrides[rate_limit.get_rate_limiter] = lambda: edge_limiter
    if flags is not None:
        app.dependency_overrides[deps.get_flag_store] = lambda: flags
    app.dependency_overrides[seam(deps, "get_spend_caps")] = lambda: caps
    app.dependency_overrides[seam(deps, "get_rate_limiter")] = lambda: limiter
    if ledger is not None:
        app.dependency_overrides[seam(deps, "get_spend_cap_ledger")] = lambda: ledger
    else:  # the production seam, unwired (the SEC-15 harness wires a fresh ledger)
        app.dependency_overrides.pop(seam(deps, "get_spend_cap_ledger"), None)
    sec.as_user(JUDGE_A)
    return Sec16(sec=sec, ledger=ledger, limiter=limiter, caps=caps, clock=clock)


def close() -> None:
    _sec15_lib.close()
