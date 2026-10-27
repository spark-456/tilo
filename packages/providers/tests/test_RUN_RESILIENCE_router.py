"""Transient overload gets a bounded retry on the same profile before fallback."""

from __future__ import annotations

import pytest
from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.errors import QuotaError, RetryableError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router


@pytest.mark.parametrize("error", [QuotaError("429"), RetryableError("503")])
def test_RUN_RESILIENCE_router_retries_same_profile_without_charging_failed_calls(providers_config, monkeypatch, error):
    waits = []
    monkeypatch.setattr("tilo_providers.router.time.sleep", waits.append)
    monkeypatch.setattr("tilo_providers.router.random.uniform", lambda _a, _b: 1.0)
    first = ScriptedModelProvider(
        "large",
        [
            ScriptedCall(outcome="error", error=error),
            ScriptedCall(outcome="error", error=error),
            ScriptedCall(text="recovered", usage={"input_tokens": 2, "output_tokens": 3}),
        ],
    )
    second = ScriptedModelProvider("medium", [ScriptedCall(text="fallback")])
    router = Router(
        providers_config, provider_for_profile={"large": first, "medium": second}.__getitem__, retry_transient=True
    )

    result = router.generate("director", GenerateRequest(prompt="hello"), budget=100)

    assert result.response and result.response.text == "recovered"
    assert waits == [2, 6]
    assert [a.profile_id for a in result.attempts] == ["large"] * 3
    assert not second.calls
    assert result.budget == pytest.approx(100 - providers_config.credits(providers_config.cost_usd("large", 2, 3)))


def test_RUN_RESILIENCE_router_falls_back_after_bounded_same_profile_retries(providers_config, monkeypatch):
    waits = []
    monkeypatch.setattr("tilo_providers.router.time.sleep", waits.append)
    monkeypatch.setattr("tilo_providers.router.random.uniform", lambda _a, _b: 1.0)
    first = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=QuotaError("429")) for _ in range(4)])
    second = ScriptedModelProvider("medium", [ScriptedCall(text="fallback")])
    router = Router(
        providers_config,
        provider_for_profile={"large": first, "medium": second}.__getitem__,
        retry_transient=True,
    )

    result = router.generate("director", GenerateRequest(prompt="hello"), budget=100)

    assert result.response and result.response.text == "fallback"
    assert waits == [2, 6, 15]
    assert [a.profile_id for a in result.attempts] == ["large"] * 4 + ["medium"]
    assert all(a.quoted_credits > 0 and a.tokens_out is None for a in result.attempts[:4])
    assert result.budget is not None and result.budget < 100
