"""PL-03 (PRD 6.4) review follow-ups for `Router.stream()` and the budget check.

- A stream falls back only while no chunk has reached the caller. Once output has started, a
  failure ends the stream with a `ProviderError` (`StreamInterruptedError`) instead of splicing a
  fresh answer from the next profile onto a partial one.
- Stream attempts are recorded like `generate()` attempts, so the Trace shows a fallback.
- The budget is checked before every call, not only the first: a fallback or cascade escalation
  that would cost more than the budget left is refused instead of being sent.
"""

from __future__ import annotations

import pytest
from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.errors import ProviderError, QuotaError
from tilo_providers.interfaces import GenerateRequest, GenerateResponse


class _ChunkThenFail(ScriptedModelProvider):
    """Streams one chunk, then raises the way the OpenAI-compatible adapter does for a bad chunk."""

    def stream(self, request: GenerateRequest):
        self.calls.append(request)
        yield GenerateResponse(text="partial from large", profile_id=self.profile_id)
        raise ProviderError("PL-02: malformed stream chunk")


def _router(config, providers):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


def test_PL_03_stream_does_not_fall_back_after_output_has_started(providers_config):
    from tilo_providers.router import StreamInterruptedError  # noqa: PLC0415

    primary = _ChunkThenFail("large", [])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="must never be reached")])
    stream = _router(providers_config, {"large": primary, "medium": fallback}).stream(
        "director", GenerateRequest(prompt="Summarise the quarter.")
    )

    received: list[str | None] = []
    with pytest.raises(StreamInterruptedError) as excinfo:
        for chunk in stream:
            received.append(chunk.text)

    assert isinstance(excinfo.value, ProviderError)
    assert received == ["partial from large"], "no second answer may be spliced onto a partial one"
    assert fallback.calls == []
    assert [(a.profile_id, a.outcome, a.error_type) for a in stream.attempts] == [("large", "error", "ProviderError")]


def test_PL_03_stream_fallback_before_first_chunk_is_recorded(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=QuotaError("rate limited"))])
    fallback = ScriptedModelProvider(
        "medium", [ScriptedCall(text="ok from medium", usage={"input_tokens": 4, "output_tokens": 2})]
    )
    stream = _router(providers_config, {"large": primary, "medium": fallback}).stream(
        "director", GenerateRequest(prompt="Summarise the quarter.")
    )

    assert [chunk.text for chunk in stream] == ["ok from medium"]
    first, second = stream.attempts
    assert (first.profile_id, first.outcome, first.error_type) == ("large", "error", "QuotaError")
    assert (second.profile_id, second.outcome, second.tokens_in, second.tokens_out) == ("medium", "ok", 4, 2)
    assert "QuotaError" in (second.reason or ""), "the Trace must say why the fallback happened"


def test_PL_03_budget_is_checked_before_a_fallback_call_too(providers_config):
    """Director: large (2.0/8.0 USD per M) then medium. A budget that covers exactly one call on
    large must not also pay for the fallback call on medium after large fails."""
    from tilo_providers.router import BudgetExceededError  # noqa: PLC0415

    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=QuotaError("rate limited"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="must never be reached")])
    request = GenerateRequest(prompt="hello there", max_output_tokens=1000)
    large_cost = providers_config.credits((2 * 2.0 + 1000 * 8.0) / 1_000_000)

    with pytest.raises(BudgetExceededError) as excinfo:
        _router(providers_config, {"large": primary, "medium": fallback}).generate(
            "director", request, budget=large_cost * 1.01
        )

    assert len(primary.calls) == 1
    assert fallback.calls == [], "the fallback call would exceed the remaining budget"
    attempts = [(a.profile_id, a.error_type) for a in excinfo.value.attempts]
    assert attempts == [("large", "QuotaError"), ("medium", "BudgetExceededError")]


def test_PL_03_router_picks_the_candidate_the_budget_can_cover(providers_config):
    """PL-03 "picks by role, capability and budget": director is large (2.0/8.0) then medium (0.5/2.0).
    A budget between their prices skips large without sending anything and completes on medium."""
    primary = ScriptedModelProvider("large", [ScriptedCall(text="must never be reached")])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="ok from medium")])
    request = GenerateRequest(prompt="Summarise the quarter.")
    tokens = primary.count_tokens(request.prompt)
    large_cost = providers_config.credits((tokens * 2.0 + 1024 * 8.0) / 1_000_000)
    medium_cost = providers_config.credits((tokens * 0.5 + 1024 * 2.0) / 1_000_000)
    assert medium_cost < 1.0 < large_cost

    result = _router(providers_config, {"large": primary, "medium": fallback}).generate("director", request, budget=1.0)

    assert (result.outcome, result.response.text) == ("ok", "ok from medium")
    assert primary.calls == [], "a candidate the budget cannot cover is never sent"
    skipped, used = result.attempts
    assert (skipped.profile_id, skipped.outcome, skipped.error_type) == ("large", "error", "BudgetExceededError")
    assert (used.profile_id, used.outcome) == ("medium", "ok")
    assert "BudgetExceededError" in (used.reason or ""), "the Trace must say why the fallback happened"
    assert result.budget == pytest.approx(1.0 - medium_cost)
