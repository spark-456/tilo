"""SEC-16 / GOLIVE-935 (BQ-SEC16-1, BQ-GOLIVE935-4): every live model call on a request or run is one unit on the uid
ledger. `SpendMeter` is held by the `MeteredRouter` and `MeteredSafety` that `deps.get_router`, `deps.get_safety` and
the run seams hand out in live mode, so a path that gets its providers there is metered by construction and a path
that cannot be metered gets the replay providers (never a live one with no meter).

One call: the guard checks the uid (403 `spend_cap_reached`, 503 replay-only), reserves `unit_reserve_minor` BEFORE the
provider is reached, and after it settles what the call cost from the usage it reported and `config/prices.yaml`
(INR minor units, rounded up, at least 1 paisa; an unpriced call settles the whole reserve), or releases the hold when
nothing reached a model, on any exception and on cancellation. A refused unit never reaches the provider."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, TypeVar

from tilo_providers.interfaces import SafetyProvider, SafetyResult
from tilo_providers.router import RouterError

from tilo_api import deps, spend

T = TypeVar("T")
# BQ-SEC16-1's default, 80 INR per US$. The market rate is higher, so this undercounts real INR (BQ-GOLIVE935-6).
INR_MINOR_PER_USD = 8000
_BYTES_PER_TOKEN = 3  # a screened text is priced at one token per three bytes: over-counted on purpose
_BILLED_ERRORS = frozenset({"OutputTruncatedError"})  # sent and ran to its cap, no usage reported


class SpendMeter:
    def __init__(
        self, guard: spend.SpendGuard, *, uid: str, run_id: str, org_id: str, unit_minor: int, config: Any
    ) -> None:
        self._guard, self.uid, self.run_id, self.org_id = guard, uid, run_id, org_id
        self.unit_minor, self._config = unit_minor, config

    def call(
        self,
        fn: Callable[[], T],
        price: Callable[[T], int | None],
        on_error: Callable[[BaseException], int | None] = lambda _exc: None,
    ) -> T:
        """Reserve, call, then settle (`price` of the result) or release (None), also when `fn` raises."""
        plan = self._begin()
        try:
            result = fn()
        except BaseException as exc:  # cancellation too: a hold never outlives its call
            self._end(plan, self._safe(on_error, exc))
            raise
        self._end(plan, self._safe(price, result))
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

    def _end(self, plan: spend.UnitPlan, minor: int | None) -> None:
        if minor is None:
            self._guard.abort_unit(plan)
        else:
            self._guard.settle_unit(plan, minor)

    def _safe(self, fn: Callable[[Any], int | None], arg: Any) -> int | None:
        try:
            return fn(arg)
        except Exception:  # unpriced: the whole reserve, never less
            return self.unit_minor

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

    def safety_minor(self, text: str, content: bytes | None) -> int:
        size = len(text.encode("utf-8")) + (len(content) if content else 0)
        profile = self._config.roles["safety"].primary
        tokens = -(-size // _BYTES_PER_TOKEN)
        return max(1, math.ceil(self._config.cost_usd(profile, tokens, 0, at=date.today()) * INR_MINOR_PER_USD))


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

        return meter.call(lambda: method(*args, **kwargs), lambda r: meter.router_minor(r.attempts), failed)

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
        )

    def redact(self, text: str) -> str:
        return self.raw.redact(text)
