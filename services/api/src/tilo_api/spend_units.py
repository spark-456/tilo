"""SEC-16 / GOLIVE-935 (BQ-SEC16-1, BQ-GOLIVE935-4): every live model call on a request or run is one unit on the uid
ledger. `SpendMeter` is held by the `MeteredRouter` and `MeteredSafety` that `deps.get_router`, `deps.get_safety` and
the run seams hand out in live mode, so a path that gets its providers there is metered by construction and a path
that cannot be metered gets the replay providers (never a live one with no meter).

One call: the guard checks the uid (403 `spend_cap_reached`, 503 replay-only), reserves `unit_reserve_minor` BEFORE the
provider is reached, and after it settles what the call cost from the usage it reported and `config/prices.yaml`
(INR minor units, rounded up, at least 1 paisa; an unpriced call settles the whole reserve), or releases the hold when
nothing reached a model, on any exception and on cancellation. A refused unit never reaches the provider. A settled
unit is also one Treasury ledger entry (`LedgerSink`, T3): after the settle, and it never undoes it."""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, TypeVar

from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage
from tilo_providers.interfaces import SafetyProvider, SafetyResult
from tilo_providers.router import RouterError

from tilo_api import deps, spend

logger = logging.getLogger("tilo_api.spend_units")
T = TypeVar("T")
# BQ-SEC16-1's default, 80 INR per US$. The market rate is higher, so this undercounts real INR (BQ-GOLIVE935-6).
INR_MINOR_PER_USD = 8000
_BYTES_PER_TOKEN = 3  # a screened text is priced at one token per three bytes: over-counted on purpose
_BILLED_ERRORS = frozenset({"OutputTruncatedError"})  # sent and ran to its cap, no usage reported
LIVE_STEPS = ("model", "safety")  # the `step` of a Treasury entry a metered unit writes (T3)
_USAGE_ATTEMPT = ("tokens_in", "tokens_out", "tokens_cached", "search_queries", "tokens_audio")  # Usage's int fields
LIVE_TASK_TYPE = "live_call"  # the `by_task_type` label the report tells that spend by
UNATTRIBUTED = ("req_", "task_", "world_")  # a meter's own run id when it could not name the task's run (T3)


def live_run_id(uid: str) -> str:
    """The person's pseudo run for live spend no world's run could be named for (T3, BQ-T3-3), as Quick's."""
    return "r_live_" + hashlib.sha256(b"live/" + uid.encode()).hexdigest()[:24]


def _count(attempt: Any, name: str) -> int:
    value = getattr(attempt, name, None)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


class LedgerSink:
    """T3 (BQ-T3-3): where a settled unit also becomes ONE Treasury ledger `commit` entry, for exactly the credits
    the cap ledger settled (minor units / `INR_MINOR_PER_USD` / `credit_usd`: nothing re-priced), keyed by the unit's
    reservation id so a retried record counts once. It runs after the settle and can never undo it: any failure is
    one ERROR line (`treasury_ledger_write_failed`, the error type only) and the request goes on."""

    def __init__(self, writer: Any, *, uid: str, org_id: str, run_id: str, credit_usd: Callable[[], float]) -> None:
        self._writer, self._uid, self._org, self._run, self._credit_usd = writer, uid, org_id, run_id, credit_usd

    def record(self, unit_id: str, minor: int, step: str, usage: Usage | None) -> None:
        try:
            credits = minor / INR_MINOR_PER_USD / self._credit_usd()
            entry = LedgerEntry(
                "commit", self._run, self._uid, self._org, datetime.now(UTC), step=step, credits=credits, usage=usage
            )
            once = getattr(self._writer, "append_once", None)
            if callable(once):
                once(f"unit_{unit_id}", entry)
            else:
                self._writer.append(entry)
        except Exception as exc:  # the ledger is a record of the spend, never a condition of it
            logger.error("treasury_ledger_write_failed (%s)", type(exc).__name__)


class SpendMeter:
    def __init__(
        self,
        guard: spend.SpendGuard,
        *,
        uid: str,
        run_id: str,
        org_id: str,
        unit_minor: int,
        config: Any,
        sink: LedgerSink | None = None,
    ) -> None:
        self._guard, self.uid, self.run_id, self.org_id = guard, uid, run_id, org_id
        self.unit_minor, self._config, self._sink = unit_minor, config, sink

    def call(
        self,
        fn: Callable[[], T],
        price: Callable[[T], int | None],
        on_error: Callable[[BaseException], int | None] = lambda _exc: None,
        *,
        step: str = "model",
        usage: Callable[[Any], Usage | None] = lambda _x: None,
    ) -> T:
        """Reserve, call, then settle (`price` of the result) or release (None), also when `fn` raises. A settled unit
        is also one Treasury entry (`step`, and the `usage` the provider reported)."""
        plan = self._begin()
        try:
            result = fn()
        except BaseException as exc:  # cancellation too: a hold never outlives its call
            self._end(plan, self._safe(on_error, exc), step, self._usage_of(usage, exc))
            raise
        self._end(plan, self._safe(price, result), step, self._usage_of(usage, result))
        return result

    def _begin(self) -> spend.UnitPlan:
        if self._guard.uid_capped(self.uid):
            raise spend.SpendCapReached
        if not self._guard.live_allowed(self.uid):
            raise deps.ReplayOnly
        plan = self._begin_unit(self.unit_minor)
        if plan.reservation is None and plan.reason == "uid_lifetime":
            # under the cap but with less than a unit left: the last call is held for what is left and settles what
            # it cost (an overrun is recorded in full); the next one finds the uid capped. Never more than one.
            if (room := self._guard.headroom_minor(self.uid)) > 0:
                plan = self._begin_unit(room)
        if plan.reservation is None:
            raise spend.SpendCapReached if plan.reason == "uid_lifetime" else deps.ReplayOnly
        return plan

    def _begin_unit(self, estimate_minor: int) -> spend.UnitPlan:
        return self._guard.begin_unit(
            "live", uid=self.uid, run_id=self.run_id, org_id=self.org_id, estimate_minor=estimate_minor,
            at=datetime.now(UTC),
        )  # fmt: skip

    def _end(self, plan: spend.UnitPlan, minor: int | None, step: str, usage: Usage | None) -> None:
        if minor is None:
            self._guard.abort_unit(plan)
            return
        self._guard.settle_unit(plan, minor)
        if self._sink is not None and plan.reservation is not None and minor > 0:
            self._sink.record(plan.reservation.id, minor, step, usage)

    def _safe(self, fn: Callable[[Any], int | None], arg: Any) -> int | None:
        try:
            return fn(arg)
        except Exception:  # unpriced: the whole reserve, never less
            return self.unit_minor

    @staticmethod
    def _usage_of(fn: Callable[[Any], Usage | None], arg: Any) -> Usage | None:
        try:
            return fn(arg)
        except Exception:  # a usage that cannot be read is no usage; the entry still records the credits
            return None

    def router_minor(self, attempts: Iterable[Any]) -> int | None:
        """INR minor units for the attempts that reached a model, None when none did (the hold is released)."""
        usd, reached = 0.0, False
        for a in attempts:
            if a.outcome == "error" and a.error_type not in _BILLED_ERRORS:
                continue  # refused before sending, or failed upstream: never charged
            reached = True
            if not (isinstance(a.tokens_in, int) and isinstance(a.tokens_out, int)) and not isinstance(
                a.search_queries, int
            ):
                return self.unit_minor  # billed but no usage reported: the whole reserve
            usd += self._config.cost_usd(
                a.profile_id, a.tokens_in or 0, a.tokens_out or 0, cached=a.tokens_cached or 0,
                units=a.search_queries or 0, audio=a.tokens_audio or 0, at=date.today(),
            )  # fmt: skip
        return max(1, math.ceil(usd * INR_MINOR_PER_USD)) if reached else None

    def router_usage(self, attempts: Iterable[Any]) -> Usage | None:
        """What the billed attempts reported, for the entry's usage: tokens summed, the last billed profile."""
        billed = [a for a in attempts if not (a.outcome == "error" and a.error_type not in _BILLED_ERRORS)]
        if not billed or not isinstance(billed[-1].profile_id, str):
            return None
        if not any(isinstance(a.tokens_in, int) or isinstance(a.search_queries, int) for a in billed):
            return None  # billed but nothing reported: the entry carries the credits and no invented tokens
        counts = [sum(_count(a, name) for a in billed) for name in _USAGE_ATTEMPT]
        return Usage(billed[-1].profile_id, *counts)

    def _screened(self, text: str, content: bytes | None) -> tuple[str, int]:
        size = len(text.encode("utf-8")) + (len(content) if content else 0)
        return self._config.roles["safety"].primary, -(-size // _BYTES_PER_TOKEN)

    def safety_minor(self, text: str, content: bytes | None) -> int:
        profile, tokens = self._screened(text, content)
        return max(1, math.ceil(self._config.cost_usd(profile, tokens, 0, at=date.today()) * INR_MINOR_PER_USD))

    def safety_usage(self, text: str, content: bytes | None) -> Usage:
        profile, tokens = self._screened(text, content)
        return Usage(profile, tokens, 0)


class MeteredRouter:
    """The Router's `generate` and `search`, each one unit. Nothing else of the Router is reachable through it (no
    `embed`, no `stream`): a call that is not metered cannot be made. `raw` is the unmetered Router, for the two
    paths that hold their own unit (Quick and the Meeting Hall)."""

    def __init__(self, raw: Any, meter: SpendMeter) -> None:
        self.raw, self._meter = raw, meter

    def _metered(self, method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        meter = self._meter

        def failed(exc: BaseException) -> int | None:
            return meter.router_minor(exc.attempts) if isinstance(exc, RouterError) else None

        return meter.call(
            lambda: method(*args, **kwargs),
            lambda r: meter.router_minor(r.attempts),
            failed,
            usage=lambda x: meter.router_usage(x.attempts),
        )

    def generate(self, *args: Any, **kwargs: Any) -> Any:
        return self._metered(self.raw.generate, *args, **kwargs)

    def search(self, *args: Any, **kwargs: Any) -> Any:
        return self._metered(self.raw.search, *args, **kwargs)


class MeteredSafety(SafetyProvider):
    """The safety screen, one unit per check at the price of the tokens it screened (Model Armor's own rate)."""

    def __init__(self, raw: SafetyProvider, meter: SpendMeter) -> None:
        self.raw, self._meter = raw, meter

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
        return self._meter.call(
            lambda: self.raw.check(text, content=content, mime_type=mime_type),
            lambda _result: self._meter.safety_minor(text, content),
            step="safety",
            usage=lambda _result: self._meter.safety_usage(text, content),
        )

    def redact(self, text: str) -> str:
        return self.raw.redact(text)
