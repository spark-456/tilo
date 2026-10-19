"""P0-RUNS-FIX: a Gemini 5xx or 429 is retried on the same profile after 2 s, 6 s and 15 s before the router falls
back, so one busy minute no longer exhausts every candidate. The delays are opt-in: only the live request router
(`tilo_api.deps.router_for_mode`) passes them, so a replay or fake router keeps its old behaviour."""

from __future__ import annotations

from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.errors import QuotaError, RequestError, RetryableError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router


def _router(providers_config, primary, fallback, waits: list[float], delays=(2.0, 6.0, 15.0)) -> Router:
    return Router(
        providers_config,
        provider_for_profile={"large": primary, "medium": fallback}.__getitem__,
        retry_delays=delays,
        sleep=waits.append,
    )


def test_P0_RUNS_FIX_a_5xx_is_retried_on_the_same_profile_with_backoff(providers_config) -> None:
    primary = ScriptedModelProvider(
        "large",
        [
            ScriptedCall(outcome="error", error=RetryableError("503 overloaded")),
            ScriptedCall(outcome="error", error=QuotaError("429 busy")),
            ScriptedCall(text="answer"),
        ],
    )
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="fallback")])
    waits: list[float] = []

    result = _router(providers_config, primary, fallback, waits).generate("director", GenerateRequest(prompt="Plan."))

    assert result.response is not None and result.response.text == "answer"
    assert waits == [2.0, 6.0] and fallback.calls == []
    assert [a.profile_id for a in result.attempts] == ["large", "large", "large"]


def test_P0_RUNS_FIX_after_three_backoffs_the_router_falls_back(providers_config) -> None:
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=RetryableError("500"))] * 4)
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="fallback")])
    waits: list[float] = []

    result = _router(providers_config, primary, fallback, waits).generate("director", GenerateRequest(prompt="Plan."))

    assert result.response is not None and result.response.text == "fallback"
    assert waits == [2.0, 6.0, 15.0] and len(primary.calls) == 4


def test_P0_RUNS_FIX_a_bad_request_is_never_retried(providers_config) -> None:
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=RequestError("400 bad"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="fallback")])
    waits: list[float] = []

    try:
        _router(providers_config, primary, fallback, waits).generate("director", GenerateRequest(prompt="Plan."))
    except RequestError:
        pass
    assert waits == []


def test_P0_RUNS_FIX_a_router_without_retry_delays_falls_back_at_once(providers_config) -> None:
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=RetryableError("503"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="fallback")])
    waits: list[float] = []
    router = Router(
        providers_config,
        provider_for_profile={"large": primary, "medium": fallback}.__getitem__,
        sleep=waits.append,
    )

    result = router.generate("director", GenerateRequest(prompt="Plan."))

    assert result.response is not None and result.response.text == "fallback" and waits == []
