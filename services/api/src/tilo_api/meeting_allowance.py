"""Existing intake allowance held atomically for one explicit minutes/follow-up operation."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tilo_api.assistant.metering import SpendLedger
from tilo_api.people_writes import Refusal


def _positive(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


class AllowanceRouter:
    """Hold the worst case before safety/model work; settle Router credits even on failed publication.

    Unknown usage conservatively consumes the sent budget. SEC-16's separate per-unit monetary
    accounting remains authoritative. This adds no price or budget configuration.
    """

    def __init__(
        self, inner: Any, *, ledger: SpendLedger, user: str, clock: Callable[[], str], cap: float, budget: float
    ) -> None:
        if not _positive(cap) or not _positive(budget):
            raise Refusal(429, "allowance_capped")
        self.inner, self.ledger = inner, ledger
        self.total = self.left = min(budget, cap)
        try:
            stamp = datetime.fromisoformat(clock().replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError
            day = stamp.astimezone(UTC).date().isoformat()
            self.hold = ledger.reserve(user, day, self.total, cap)
        except Exception:
            raise Refusal(429, "allowance_capped") from None
        if self.hold is None:
            raise Refusal(429, "allowance_capped")

    def generate(self, role: str, request: Any, *, budget: float) -> Any:
        if self.hold is None or not _positive(budget) or self.left <= 0:
            raise Refusal(429, "allowance_capped")
        sent = min(budget, self.left)
        self.left -= sent  # conservatively consumed before invocation
        try:
            result = self.inner.generate(role, request, budget=sent)
        except Exception:
            raise Refusal(429, "allowance_capped") from None
        remaining: Any = getattr(result, "budget", None)
        if type(remaining) in (int, float) and math.isfinite(remaining) and 0 <= remaining <= sent:
            self.left += remaining
        return result

    def close(self) -> None:
        if self.hold is not None:
            hold, self.hold = self.hold, None
            try:
                if self.left == self.total:
                    self.ledger.release(hold)
                else:
                    self.ledger.commit(hold, self.total - self.left)
            except Exception:
                raise Refusal(429, "allowance_capped") from None

    def __enter__(self) -> AllowanceRouter:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def allowance_router(
    router: Any, *, ledger: SpendLedger, user: str, clock: Callable[[], str], cap: float, budget: float
) -> AllowanceRouter:
    if ledger is None:
        raise Refusal(429, "allowance_capped")
    return AllowanceRouter(router, ledger=ledger, user=user, clock=clock, cap=cap, budget=budget)
