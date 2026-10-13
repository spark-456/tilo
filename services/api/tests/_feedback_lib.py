"""Helpers for the SEC-16 beta-allowance feedback tests (`POST /v1/feedback`; see API_SPEND_FEEDBACK.md).

Named `_feedback_lib` for the same global-bare-module-name reason as `_sec16_lib.py`. Nothing here is business logic:
the store under test is the production `tilo_api.feedback.InMemoryFeedbackStore` (imported lazily, so a missing module
fails each test and not collection), wrapped by a spy that only records calls. The clock is a fake that returns the
`common#timestamp` strings `deps.get_clock()` returns.

No network, no paid call, no secret.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from _clint1_lib import seam

CONTEXT = "lifetime_cap"
GOOD_TEXT = "I liked how the plan was explained, but the approval step was hard to find."
GOOD_BODY: dict[str, Any] = {"text": GOOD_TEXT, "context": CONTEXT}
START = datetime(2026, 10, 8, 9, 0, 0, tzinfo=UTC)

# The numbers API_SPEND_FEEDBACK.md fixes (the PRD names none). They are literals here on purpose: a change to
# any of them is a change to the spec.
MAX_TEXT_CHARS = 2000
MAX_RAW_CHARS = 8000
PER_HOUR = 5
LIFETIME_MAX = 20
HOUR_S = 3600


class FakeNow:
    """`deps.get_clock()` replacement: calling it returns the current fake time as an RFC 3339 UTC string with
    exactly three fractional digits (`common#timestamp`)."""

    def __init__(self, start: datetime = START) -> None:
        self.at = start
        self.reads = 0

    def __call__(self) -> str:
        self.reads += 1
        return self.at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.at.microsecond // 1000:03d}Z"

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


class SpyFeedbackStore:
    """Delegates to the production in-memory store and records every call name."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if not callable(target):
            return target

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return target(*args, **kwargs)

        return call


def make_store() -> Any:
    from tilo_api.feedback import InMemoryFeedbackStore  # noqa: PLC0415

    return InMemoryFeedbackStore()


def install(h: Any, *, store: Any = None, clock: Any = None) -> tuple[SpyFeedbackStore, FakeNow]:
    """Wires the two seams the route reads (`deps.get_feedback_store`, `deps.get_clock`) on the harness's app.
    `h` is a `Sec16` (or `Sec15`) harness; `_sec16_lib.close()` clears the overrides afterwards."""
    from tilo_api import app, deps  # noqa: PLC0415

    spy = SpyFeedbackStore(store if store is not None else make_store())
    now = clock if clock is not None else FakeNow()
    app.dependency_overrides[seam(deps, "get_feedback_store")] = lambda: spy
    app.dependency_overrides[deps.get_clock] = lambda: now
    return spy, now


def post(h: Any, body: Any = None, **kwargs: Any) -> Any:
    """One `POST /v1/feedback` with a JSON body (the good one by default)."""
    return h.client.post("/v1/feedback", json=GOOD_BODY if body is None else body, **kwargs)


def with_text(text: Any) -> dict[str, Any]:
    return {"text": text, "context": CONTEXT}
