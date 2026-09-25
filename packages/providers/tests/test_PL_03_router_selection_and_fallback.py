"""PL-03 (PRD 6.4): "Router picks by role, capability and budget; falls back
on errors, quota or missing capability." Acceptance test: "Kill the primary
in a test; the call completes on the fallback and the Trace records both."

Public interface under test: `tilo_providers.router.Router.generate()`.
Ticket P0-06 item 1 and its security hand-over from P0-05 ("the router must
treat every ProviderError subtype explicitly; no raw exception from an
adapter escapes the router"):

- QuotaError / RetryableError: the primary is actually called, fails, and
  the router retries on the role's fallback profile. The call record lists
  both attempts (profile, error type, latency) -- exactly what the Trace's
  `trace` field needs (PRD 9.3).
- A missing capability is resolved *before* any call is made: the router
  never attempts a profile that does not declare the required capability,
  so the call record shows a single attempt, straight on the capable
  profile.
- RequestError does not fall back (the request itself is bad; retrying a
  different profile will not help) -- it propagates.
- SafetyError does not fall back either, but it is not raised as a bug: it
  comes back as a normal `RouterResult` with `outcome="safety_blocked"`.
- A raw, non-`ProviderError` exception from an adapter (a bug) is never
  silently swallowed or treated as a retryable/fallback-worthy error -- it
  propagates unchanged, so the bug stays visible.
- An adapter also raises the base `ProviderError` itself (malformed response
  body, bad stream chunk, bad tool-call JSON, missing api_key_env) -- that
  is provider trouble, not caller trouble, so `generate()`, `stream()` and
  `embed()` all give it the same explicit fallback policy as QuotaError/
  RetryableError, recorded as an attempt rather than escaping unhandled.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    capability_models_config,
    prices_config_for,
    write_providers_config,
)
from tilo_providers.errors import ProviderError, QuotaError, RequestError, RetryableError, SafetyError
from tilo_providers.interfaces import Capability, GenerateRequest


def _router(config, providers: dict[str, ScriptedModelProvider]):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


@pytest.mark.parametrize(
    ("error_cls", "error_message"),
    [(QuotaError, "rate limited"), (RetryableError, "upstream 503")],
    ids=["quota_error", "retryable_error"],
)
def test_PL_03_primary_failure_completes_on_fallback_and_records_both(providers_config, error_cls, error_message):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=error_cls(error_message))])
    fallback = ScriptedModelProvider(
        "medium", [ScriptedCall(text="ok from medium", usage={"input_tokens": 5, "output_tokens": 3})]
    )
    router = _router(providers_config, {"large": primary, "medium": fallback})

    result = router.generate("director", GenerateRequest(prompt="Summarise the quarter."))

    assert result.outcome == "ok"
    assert result.response is not None
    assert result.response.text == "ok from medium"

    # PRD 9.3 trace field: the call record must carry both attempts so the
    # harness can put {model_role, profile, tokens_in, tokens_out, latency_ms}
    # into the TiloEvent trace field for each one.
    assert [attempt.profile_id for attempt in result.attempts] == ["large", "medium"]
    primary_attempt, fallback_attempt = result.attempts
    assert primary_attempt.outcome != "ok"
    assert primary_attempt.error_type == error_cls.__name__
    assert primary_attempt.latency_ms >= 0
    assert fallback_attempt.outcome == "ok"
    assert fallback_attempt.tokens_in == 5
    assert fallback_attempt.tokens_out == 3

    assert len(primary.calls) == 1, "the primary must actually be called before falling back"
    assert len(fallback.calls) == 1


def test_PL_03_missing_capability_goes_straight_to_capable_profile_single_attempt(tmp_path):
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    models_path, prices_path = write_providers_config(
        tmp_path,
        capability_models_config(),
        prices_config_for({"text-only": (0.1, 0.2), "vision-capable": (0.5, 1.0)}),
    )
    config = load_providers_config(models_path, prices_path)

    primary = ScriptedModelProvider("text-only", [ScriptedCall(text="must never be reached")])
    capable = ScriptedModelProvider("vision-capable", [ScriptedCall(text="described the image")])
    router = _router(config, {"text-only": primary, "vision-capable": capable})

    result = router.generate(
        "seer", GenerateRequest(prompt="Describe this photo."), required_capability=Capability.VISION
    )

    assert result.outcome == "ok"
    assert result.response is not None
    assert result.response.text == "described the image"
    # "Goes straight to" -- exactly one attempt, and it is never the
    # capability-lacking primary: the router must not burn a call on a
    # profile it already knows cannot serve the request.
    assert [attempt.profile_id for attempt in result.attempts] == ["vision-capable"]
    assert primary.calls == [], "the primary lacks Capability.VISION and must never be called"
    assert len(capable.calls) == 1


def test_PL_03_request_error_from_primary_is_not_retried_on_fallback(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=RequestError("bad request"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="must never be reached")])
    router = _router(providers_config, {"large": primary, "medium": fallback})

    with pytest.raises(RequestError):
        router.generate("director", GenerateRequest(prompt="Summarise the quarter."))

    assert len(primary.calls) == 1
    assert fallback.calls == [], "a RequestError means retrying is pointless -- no silent fallback"


def test_PL_03_safety_block_is_returned_as_a_safety_outcome_not_a_fallback(providers_config):
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=SafetyError("blocked on safety"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="must never be reached")])
    router = _router(providers_config, {"large": primary, "medium": fallback})

    result = router.generate("director", GenerateRequest(prompt="Summarise the quarter."))

    assert result.outcome == "safety_blocked"
    assert result.response is None
    assert len(result.attempts) == 1
    assert result.attempts[0].profile_id == "large"
    assert result.attempts[0].error_type == "SafetyError"
    assert fallback.calls == [], "a safety block does not fall back silently"


def test_PL_03_malformed_response_provider_error_is_recorded_and_handled(providers_config):
    """Security hand-over from P0-05: an adapter also raises the base `ProviderError` itself (not
    only its four named subclasses) for a provider-side malfunction -- a malformed response body,
    a bad stream chunk, bad tool-call JSON, a missing api_key_env. None of that is the caller's
    fault, so the router must give it the same explicit policy as QuotaError/RetryableError: record
    it as an attempt (`error_type` set) and fall back, rather than let it escape unhandled."""
    primary = ScriptedModelProvider(
        "large", [ScriptedCall(outcome="error", error=ProviderError("PL-02: malformed response body"))]
    )
    fallback = ScriptedModelProvider(
        "medium", [ScriptedCall(text="ok from medium", usage={"input_tokens": 5, "output_tokens": 3})]
    )
    router = _router(providers_config, {"large": primary, "medium": fallback})

    result = router.generate("director", GenerateRequest(prompt="Summarise the quarter."))

    assert result.outcome == "ok"
    assert result.response is not None
    assert result.response.text == "ok from medium"
    assert [attempt.profile_id for attempt in result.attempts] == ["large", "medium"]
    primary_attempt, fallback_attempt = result.attempts
    assert primary_attempt.outcome == "error"
    assert primary_attempt.error_type == "ProviderError"
    assert fallback_attempt.outcome == "ok"
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_PL_03_stream_falls_back_on_base_provider_error(providers_config):
    """Same gap, in `stream()`: a base `ProviderError` from the primary must not escape the
    router -- it falls back to the next candidate, same as `generate()`."""
    from tilo_providers.router import Router  # noqa: PLC0415

    primary = ScriptedModelProvider(
        "large", [ScriptedCall(outcome="error", error=ProviderError("PL-02: malformed stream chunk"))]
    )
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="ok from medium")])
    router = Router(providers_config, provider_for_profile={"large": primary, "medium": fallback}.__getitem__)

    chunks = list(router.stream("director", GenerateRequest(prompt="Summarise the quarter.")))

    assert [chunk.text for chunk in chunks] == ["ok from medium"]
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_PL_03_embed_falls_back_on_base_provider_error(providers_config):
    """Same gap, in `embed()`."""
    from tilo_providers.router import Router  # noqa: PLC0415

    class _EmbedProvider(ScriptedModelProvider):
        def __init__(
            self, profile_id: str, *, error: Exception | None = None, vectors: list[list[float]] | None = None
        ):
            super().__init__(profile_id, [])
            self._error = error
            self._vectors = vectors
            self.embed_calls: list[Any] = []

        def embed(self, request: Any) -> Any:
            self.embed_calls.append(request)
            if self._error is not None:
                raise self._error
            return {"vectors": self._vectors}

    primary = _EmbedProvider("large", error=ProviderError("PL-02: provider response missing field"))
    fallback = _EmbedProvider("medium", vectors=[[0.1, 0.2]])
    router = Router(providers_config, provider_for_profile={"large": primary, "medium": fallback}.__getitem__)

    result = router.embed("director", {"input": ["hello"]})

    assert result == {"vectors": [[0.1, 0.2]]}
    assert len(primary.embed_calls) == 1
    assert len(fallback.embed_calls) == 1


def test_PL_03_non_provider_error_from_an_adapter_is_not_swallowed(providers_config):
    """Security hand-over from P0-05: the router treats every ProviderError
    subtype explicitly. A bug that makes an adapter raise something that is
    *not* one of the four documented subtypes must not be mistaken for a
    fallback-worthy error and silently retried -- it has to stay visible."""
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=RuntimeError("adapter bug"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="must never be reached")])
    router = _router(providers_config, {"large": primary, "medium": fallback})

    with pytest.raises(RuntimeError, match="adapter bug"):
        router.generate("director", GenerateRequest(prompt="Summarise the quarter."))

    assert fallback.calls == []
