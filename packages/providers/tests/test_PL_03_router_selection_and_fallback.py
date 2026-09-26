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
  silently swallowed: PL-03 "falls back on errors", so it is recorded as an
  attempt with its own type (visible in the Trace) and, if every candidate
  fails, kept as the `__cause__` of the `RouterError` the router raises --
  no raw adapter exception escapes the router (ticket P0-06 review).
- An adapter also raises the base `ProviderError` itself (malformed response
  body, bad stream chunk, bad tool-call JSON, missing api_key_env) -- that
  is provider trouble, not caller trouble, so `generate()`, `stream()` and
  `embed()` all give it the same explicit fallback policy as QuotaError/
  RetryableError, recorded as an attempt rather than escaping unhandled.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    capability_models_config,
    models_config,
    prices_config,
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


def test_PL_03_embed_falls_back_on_base_provider_error_and_records_both_attempts(providers_config):
    """Same gap, in `embed()`: a base `ProviderError` from the primary must not escape the router, and
    (review follow-up, ticket P0-06 audit) `embed()` must go through the same `_attempt`/`_finish`/
    `_fall_back` path as `generate()`/`stream()` -- the PRD 9.3 trace field needs both attempts, exactly
    as the "kill the primary" acceptance test already checks for generate()."""
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

    assert result.embedding == {"vectors": [[0.1, 0.2]]}
    assert len(primary.embed_calls) == 1
    assert len(fallback.embed_calls) == 1

    # PRD 9.3 trace field: both attempts must be on the record, primary as an error, fallback as ok.
    assert [attempt.profile_id for attempt in result.attempts] == ["large", "medium"]
    primary_attempt, fallback_attempt = result.attempts
    assert primary_attempt.outcome == "error"
    assert primary_attempt.error_type == "ProviderError"
    assert primary_attempt.latency_ms >= 0
    assert fallback_attempt.outcome == "ok"


def test_PL_03_embed_missing_capability_goes_straight_to_capable_profile(tmp_path):
    """Review follow-up (ticket P0-06 audit): the same capability filter that keeps `generate()`/
    `stream()` from ever calling a candidate lacking `required_capability` applies to `embed()` too --
    proven directly on `embed()`'s own path, not assumed from the generate() test above."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    models_path, prices_path = write_providers_config(
        tmp_path,
        capability_models_config(),
        prices_config_for({"text-only": (0.1, 0.2), "vision-capable": (0.5, 1.0)}),
    )
    config = load_providers_config(models_path, prices_path)

    class _EmbedProvider(ScriptedModelProvider):
        def __init__(self, profile_id: str, *, vectors: list[list[float]] | None = None):
            super().__init__(profile_id, [])
            self._vectors = vectors
            self.embed_calls: list[Any] = []

        def embed(self, request: Any) -> Any:
            self.embed_calls.append(request)
            return {"vectors": self._vectors}

    primary = _EmbedProvider("text-only", vectors=[[9.9]])
    capable = _EmbedProvider("vision-capable", vectors=[[0.1, 0.2]])
    router = Router(config, provider_for_profile={"text-only": primary, "vision-capable": capable}.__getitem__)

    result = router.embed("seer", {"input": ["describe this image"]}, required_capability=Capability.VISION)

    assert result.embedding == {"vectors": [[0.1, 0.2]]}
    assert [attempt.profile_id for attempt in result.attempts] == ["vision-capable"]
    assert primary.embed_calls == [], "the primary lacks Capability.VISION and must never be called"
    assert len(capable.embed_calls) == 1


def test_PL_03_embed_through_the_real_factory_path_records_and_replays(tmp_path, monkeypatch):
    """Review follow-up (ticket P0-06): every `embed()` test above builds its providers through a
    scripted `provider_for_profile` double, so none of them ever go through `Router`'s *real* factory
    path -- `Router(config, fixtures_dir=...)`, which resolves a profile with `tilo_providers.factory.
    build_provider`. For any profile that is not `provider: fake`, that wraps the adapter in a
    `RecordReplayProvider` (`tilo_providers.replay`), and its `embed()` used to be a bare
    `NotImplementedError` -- not one of the `ProviderError` subtypes `Router.embed`'s except clause
    catches, so the real exception would have escaped the router unhandled, leaving the first attempt
    recorded as "ok" and no fallback/RouterError. This drives that exact path: a role whose primary
    profile is `provider: google` (never installed in this environment -- see test_EFF_01's module
    docstring), replayed from a recording seeded on disk in the exact shape `RecordReplayProvider`
    itself writes (`embed_recording_key`-keyed), with `LIVE` unset (as dev/CI always run) -- and
    `GOOGLE_CLOUD_PROJECT` deliberately absent, so a mistaken live attempt fails loudly with a KeyError
    instead of silently succeeding (a `sys.modules` check on the adapter module would be unreliable here:
    another test file in the same session may have imported it already; `models_config`/`prices_config`
    are imported at module level, alongside this file's other `conftest` imports, for the same reason)."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.replay import embed_recording_key  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    monkeypatch.delenv("LIVE", raising=False)
    monkeypatch.delenv("TILO_RECORD", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    models = models_config()  # BASE_MODELS profiles are all `provider: fake`; "director" primary is "large"
    models["profiles"]["large"]["provider"] = "google"
    models_path, prices_path = write_providers_config(tmp_path, models, prices_config())
    config = load_providers_config(models_path, prices_path)

    fixtures_dir = tmp_path / "fixtures"
    embed_request = {"input": ["hello"]}
    key = embed_recording_key("director", "large", embed_request)
    recording_dir = fixtures_dir / "model-recordings" / "director"
    recording_dir.mkdir(parents=True)
    (recording_dir / f"embed-{key}.json").write_text(
        json.dumps({"role": "director", "profile": "large", "key": key, "embedding": {"vectors": [[0.5, 0.25]]}}),
        encoding="utf-8",
    )

    router = Router(config, fixtures_dir=fixtures_dir)
    result = router.embed("director", embed_request)

    assert result.embedding == {"vectors": [[0.5, 0.25]]}
    # A single "ok" attempt on the primary -- no NotImplementedError, no fallback, no RouterError.
    assert [attempt.profile_id for attempt in result.attempts] == ["large"]
    assert result.attempts[0].outcome == "ok"


def test_PL_03_non_provider_error_from_an_adapter_is_not_swallowed(providers_config):
    """Security hand-over from P0-05, as revised by the P0-06 review: a bug that makes an adapter raise
    something that is *not* a `ProviderError` must stay visible, but must not escape the router raw
    either. It is recorded as an attempt under its own type, the router falls back (PL-03: "falls back
    on errors"), and when every candidate fails the bug is the `__cause__` of the RouterError raised."""
    from tilo_providers.router import RouterExhaustedError  # noqa: PLC0415

    bug = RuntimeError("adapter bug")
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=bug)])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="ok from medium")])
    result = _router(providers_config, {"large": primary, "medium": fallback}).generate(
        "director", GenerateRequest(prompt="Summarise the quarter.")
    )

    assert [(a.profile_id, a.outcome, a.error_type) for a in result.attempts] == [
        ("large", "error", "RuntimeError"),
        ("medium", "ok", None),
    ]
    assert "RuntimeError" in (result.attempts[1].reason or ""), "the Trace must say why the fallback happened"

    both_broken = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=bug)] * 2)
    with pytest.raises(RouterExhaustedError) as excinfo:
        _router(providers_config, {"large": both_broken, "medium": both_broken}).generate(
            "director", GenerateRequest(prompt="Summarise the quarter.")
        )
    assert excinfo.value.__cause__ is bug
    assert [a.error_type for a in excinfo.value.attempts] == ["RuntimeError", "RuntimeError"]


def test_PL_03_request_error_after_a_fallback_carries_every_attempt(providers_config):
    """Review follow-up: the primary fails with QuotaError, the fallback rejects the request. Both
    calls were made, so the raised error still is a RequestError (no further fallback) but also a
    router error carrying both attempts for the PRD 9.3 trace, with the adapter's error as cause."""
    from tilo_providers.router import RouterError  # noqa: PLC0415

    rejected = RequestError("400 bad request")
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=QuotaError("rate limited"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(outcome="error", error=rejected)])
    router = _router(providers_config, {"large": primary, "medium": fallback})

    with pytest.raises(RequestError) as excinfo:
        router.generate("director", GenerateRequest(prompt="Summarise the quarter."))

    assert isinstance(excinfo.value, RouterError)
    assert excinfo.value.__cause__ is rejected
    assert [(a.profile_id, a.outcome, a.error_type) for a in excinfo.value.attempts] == [
        ("large", "error", "QuotaError"),
        ("medium", "error", "RequestError"),
    ]


@pytest.mark.parametrize("error_cls", [RequestError, SafetyError])
def test_PL_03_stream_request_or_safety_error_carries_every_attempt(providers_config, error_cls):
    from tilo_providers.router import RouterError  # noqa: PLC0415

    original = error_cls("refused")
    primary = ScriptedModelProvider("large", [ScriptedCall(outcome="error", error=QuotaError("rate limited"))])
    fallback = ScriptedModelProvider("medium", [ScriptedCall(outcome="error", error=original)])
    stream = _router(providers_config, {"large": primary, "medium": fallback}).stream(
        "director", GenerateRequest(prompt="Summarise the quarter.")
    )

    with pytest.raises(error_cls) as excinfo:
        list(stream)

    assert isinstance(excinfo.value, RouterError)
    assert excinfo.value.__cause__ is original
    assert [a.profile_id for a in excinfo.value.attempts] == ["large", "medium"]
