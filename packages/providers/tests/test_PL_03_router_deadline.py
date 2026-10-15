"""PL-03 / NFR-03 / NFR-22 (live defect 15 Oct 2026, tilo-api-00062): a Gemini 503 on the primary made one intake
take 122.6 s, past the web's 120 s wait. A caller can now give `Router.generate` a `Deadline`: no attempt starts after
it, each attempt waits at most its share of what is left (the primary a configured share, the last candidate the
rest), a slow or failed primary falls back on the cascade instead of re-waiting the whole time, and when the time is
gone the router raises `RouterDeadlineError` with every attempt recorded for the Trace. Fakes only, no network."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.errors import RetryableError
from tilo_providers.interfaces import GenerateRequest, GenerateResponse


class _Slow(ScriptedModelProvider):
    """Sleeps before it answers (or raises), like a live model that is slow to say 503 or to reply."""

    def __init__(self, profile_id: str, delay: float, script: list[ScriptedCall]) -> None:
        super().__init__(profile_id, script)
        self._delay = delay
        self.release = threading.Event()

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.release.wait(self._delay)
        return super().generate(request)


def _router(config: Any, providers: dict[str, ScriptedModelProvider]):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


def _deadline(seconds: float, share: float = 0.5):
    from tilo_providers.router import Deadline  # noqa: PLC0415

    return Deadline.after(seconds, share)


def test_PL_03_a_503_on_the_primary_falls_back_inside_the_deadline_and_records_why(providers_config):
    primary = _Slow("large", 0.05, [ScriptedCall(outcome="error", error=RetryableError("503 (fake)"))])
    fallback = _Slow("medium", 0.05, [ScriptedCall(text="plan from medium")])
    router = _router(providers_config, {"large": primary, "medium": fallback})
    start = time.monotonic()

    result = router.generate("director", GenerateRequest(prompt="Plan."), deadline=_deadline(5.0))

    assert result.response is not None and result.response.text == "plan from medium"
    assert [a.profile_id for a in result.attempts] == ["large", "medium"]
    assert result.attempts[0].error_type == "RetryableError"
    assert result.attempts[1].reason == "fallback after RetryableError"
    assert time.monotonic() - start < 2.0


def test_PL_03_a_primary_that_hangs_gets_only_its_share_then_the_fallback_answers(providers_config):
    primary = _Slow("large", 30.0, [ScriptedCall(text="too late")])
    fallback = _Slow("medium", 0.0, [ScriptedCall(text="plan from medium")])
    router = _router(providers_config, {"large": primary, "medium": fallback})
    start = time.monotonic()

    try:
        result = router.generate("director", GenerateRequest(prompt="Plan."), deadline=_deadline(1.0, share=0.3))
    finally:
        primary.release.set()

    assert result.response is not None and result.response.text == "plan from medium"
    assert result.attempts[0].error_type == "AttemptTimeoutError"
    assert result.attempts[1].reason == "fallback after AttemptTimeoutError"
    assert time.monotonic() - start < 1.0, "the primary may use its share, not the whole deadline"


def test_PL_03_when_every_candidate_is_slow_the_router_raises_the_deadline_error_in_time(providers_config):
    from tilo_providers.router import RouterDeadlineError, RouterExhaustedError  # noqa: PLC0415

    primary = _Slow("large", 30.0, [ScriptedCall(text="too late")])
    fallback = _Slow("medium", 30.0, [ScriptedCall(text="too late")])
    router = _router(providers_config, {"large": primary, "medium": fallback})
    start = time.monotonic()

    try:
        with pytest.raises(RouterDeadlineError) as caught:
            router.generate("director", GenerateRequest(prompt="Plan."), deadline=_deadline(0.6, share=0.5))
    finally:
        primary.release.set()
        fallback.release.set()

    assert isinstance(caught.value, RouterExhaustedError)
    assert [a.profile_id for a in caught.value.attempts] == ["large", "medium"]
    assert {a.error_type for a in caught.value.attempts} == {"AttemptTimeoutError"}
    assert time.monotonic() - start < 1.5, "no late result: the error comes at the deadline"


def test_PL_03_no_attempt_starts_after_the_deadline(providers_config):
    from tilo_providers.router import RouterDeadlineError  # noqa: PLC0415

    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=RetryableError("503 (fake)"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="never asked")])
    router = _router(providers_config, {"large": primary, "medium": fallback})

    with pytest.raises(RouterDeadlineError):
        router.generate("director", GenerateRequest(prompt="Plan."), deadline=_deadline(0.0))

    assert primary.calls == [] and fallback.calls == []


def test_PL_03_without_a_deadline_the_call_is_made_on_the_callers_thread(providers_config):
    seen: list[str] = []

    class _Names(ScriptedModelProvider):
        def generate(self, request: GenerateRequest) -> GenerateResponse:
            seen.append(threading.current_thread().name)
            return super().generate(request)

    router = _router(providers_config, {"large": _Names("large", [ScriptedCall()])})

    router.generate("director", GenerateRequest(prompt="Plan."))

    assert seen == [threading.current_thread().name]
