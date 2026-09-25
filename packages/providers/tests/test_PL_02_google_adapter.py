"""PL-02 (PRD 6.4): "Two adapters ship: `google` (default) and a generic
OpenAI-compatible adapter" -- "Conformance suite passes on the default
profiles". Ticket P0-05 item 1: google adapter against Agent Platform /
Vertex (PRD 6.5 "Gemini through the global endpoint"), implementing
`generate`, `stream`, `embed`, `count_tokens`, `capabilities`, `price`;
structured output and tool calling; error mapping to quota/retryable/
request/safety. "Tested with mocked transport or recorded responses only."

Public interface under test: `ModelProvider.generate/stream/count_tokens/
capabilities` (PRD 6.4) via `tilo_providers.google_adapter.
GoogleModelProvider`. The Google Gen AI SDK is faked at the `sys.modules`
boundary (`_fake_genai_sdk.py`) and a `FakeClient` is injected through the
constructor -- no real SDK, no network (see conftest.py's
`block_non_local_sockets`).

Interface assumption (see report): P0-04's `GenerateRequest`/
`GenerateResponse` (`tilo_providers.interfaces`) are deliberately thin and
have no field for tool-call results or usage tokens yet. These tests assume
`GenerateResponse` gains two optional fields the adapter must populate --
`tool_calls: list[dict] | None` and `usage: dict[str, int] | None` -- since
PL-02's conformance set requires both and P0-04's own docs say "adapters
(P0-05) implement these" interfaces. Until implemented, every test below
fails at `from tilo_providers.google_adapter import GoogleModelProvider`
(ModuleNotFoundError), which is the right failure now.

Constructor assumption (see report): `GoogleModelProvider(profile,
profile_id, project, location, client=None)`, where `client` is an
already-constructed `genai.Client`-shaped object, injected here as a
`FakeClient` -- `client=None` is the only case that would build a real one
(never exercised by these tests).
"""

from __future__ import annotations

import json

import pytest
from _fake_genai_sdk import (
    FakeAPIError,
    FakeClient,
    FakeCountTokensResponse,
    FakeFunctionCall,
    FakeGenerateContentResponse,
    FakeModelsAPI,
    FakePromptFeedback,
    FakeUsageMetadata,
)
from tilo_contracts import ProvidersProfile
from tilo_providers.interfaces import Capability, GenerateRequest, ModelProvider

PROJECT = "demo-tilo"
LOCATION = "global"  # PRD 6.5: Gemini through the global endpoint


def _profile(**overrides: object) -> ProvidersProfile:
    fields: dict[str, object] = {
        "provider": "google",
        "model": "gemini-3.8-flash",
        "context": 1_000_000,
        "caps": ["json", "tools", "thinking"],
    }
    fields.update(overrides)
    return ProvidersProfile.model_validate(fields)


def _provider(models_api: FakeModelsAPI, *, profile: ProvidersProfile | None = None, profile_id: str = "flash-38"):
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    return GoogleModelProvider(
        profile=profile or _profile(),
        profile_id=profile_id,
        project=PROJECT,
        location=LOCATION,
        client=FakeClient(models_api),
    )


def test_PL_02_google_adapter_conforms_to_model_provider(fake_genai_sdk):
    provider = _provider(FakeModelsAPI())
    assert isinstance(provider, ModelProvider)


def test_PL_02_google_adapter_generate_returns_structured_json_output(fake_genai_sdk):
    """PL-02 "structured output": `GenerateRequest.response_schema` must
    reach the SDK as `GenerateContentConfig(response_mime_type=
    "application/json", response_schema=...)` -- not merely pass unmodified
    JSON text through, which a caller with no way to ask for JSON at all
    would also satisfy."""
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "population": {"type": "integer"}},
    }
    payload = '{"name": "Singapore", "population": 5700000}'
    models_api = FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text=payload))
    provider = _provider(models_api, profile=_profile(caps=["json"]))

    response = provider.generate(GenerateRequest(prompt="Describe Singapore as JSON.", response_schema=schema))

    assert response.text == payload
    assert json.loads(response.text) == {"name": "Singapore", "population": 5700000}
    assert response.profile_id == "flash-38"
    call = models_api.calls[0]
    assert call["model"] == "gemini-3.8-flash", "PL-01: the profile's model id, never hardcoded"
    config = call["config"]
    assert config is not None, "PL-02: structured output must reach the SDK's GenerateContentConfig"
    assert config.response_mime_type == "application/json"
    assert config.response_schema == schema


def test_PL_02_google_adapter_generate_json_mode_without_a_schema(fake_genai_sdk):
    """PL-02 JSON mode with no schema (`json_mode=True`, no
    `response_schema`) still sets `response_mime_type` on the SDK config."""
    models_api = FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text="{}"))
    provider = _provider(models_api, profile=_profile(caps=["json"]))

    provider.generate(GenerateRequest(prompt="Reply with JSON.", json_mode=True))

    config = models_api.calls[0]["config"]
    assert config is not None
    assert config.response_mime_type == "application/json"
    assert not hasattr(config, "response_schema")


def test_PL_02_google_adapter_generate_maps_a_tool_call(fake_genai_sdk):
    """PL-02 "tool calling": a `GenerateRequest.tools` declaration reaches
    the SDK call, and a function-call response is mapped onto
    `GenerateResponse.tool_calls`."""
    function_call_response = FakeGenerateContentResponse(
        text=None,
        function_calls=[FakeFunctionCall(name="get_weather", args={"location": "Boston"})],
    )
    models_api = FakeModelsAPI(generate_content_result=function_call_response)
    provider = _provider(models_api, profile=_profile(caps=["tools"]))
    tool_schema = {
        "type": "function",
        "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"location": {}}}},
    }

    response = provider.generate(GenerateRequest(prompt="Weather in Boston?", tools=[tool_schema]))

    assert response.tool_calls == [{"name": "get_weather", "args": {"location": "Boston"}}]
    config = models_api.calls[0]["config"]
    assert config is not None, "PL-02: the tool declaration must reach the SDK's GenerateContentConfig"


def test_PL_02_google_adapter_generate_reports_usage_tokens(fake_genai_sdk):
    usage = FakeUsageMetadata(prompt_token_count=12, candidates_token_count=8, total_token_count=20)
    models_api = FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text="hi", usage_metadata=usage))
    provider = _provider(models_api)

    response = provider.generate(GenerateRequest(prompt="hi"))

    assert response.usage == {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20}


def test_PL_02_google_adapter_count_tokens(fake_genai_sdk):
    models_api = FakeModelsAPI(count_tokens_result=FakeCountTokensResponse(total_tokens=7))
    provider = _provider(models_api)

    assert provider.count_tokens("why is the sky blue?") == 7
    assert models_api.calls[0] == {
        "method": "count_tokens",
        "model": "gemini-3.8-flash",
        "contents": "why is the sky blue?",
    }


def test_PL_02_google_adapter_capabilities_match_the_profile(fake_genai_sdk):
    provider = _provider(FakeModelsAPI(), profile=_profile(caps=["json", "tools", "vision"]))

    assert provider.capabilities() == {Capability.JSON, Capability.TOOLS, Capability.VISION}


@pytest.mark.parametrize(
    ("status_code", "expected_error_name"),
    [(429, "QuotaError"), (500, "RetryableError"), (503, "RetryableError"), (400, "RequestError")],
    ids=["429-quota", "500-retryable", "503-retryable", "400-request"],
)
def test_PL_02_google_adapter_maps_api_errors(fake_genai_sdk, status_code, expected_error_name):
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    expected_error = getattr(provider_errors, expected_error_name)
    models_api = FakeModelsAPI(generate_content_error=FakeAPIError(status_code, "boom"))
    provider = _provider(models_api)

    with pytest.raises(expected_error) as excinfo:
        provider.generate(GenerateRequest(prompt="hi"))

    assert "boom" in str(excinfo.value)


def test_PL_02_google_adapter_maps_a_safety_block_to_safety_error(fake_genai_sdk):
    """PRD 10.4 policy conditions read "no safety flags"; the adapter must
    surface a blocked response as the safety error type, not as ordinary
    text (honesty rule: never invent output the model did not produce)."""
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    blocked = FakeGenerateContentResponse(text=None, prompt_feedback=FakePromptFeedback(block_reason="SAFETY"))
    models_api = FakeModelsAPI(generate_content_result=blocked)
    provider = _provider(models_api)

    with pytest.raises(provider_errors.SafetyError):
        provider.generate(GenerateRequest(prompt="something unsafe"))


def test_PL_02_google_adapter_stream_yields_chunks_that_concatenate_to_the_full_text(fake_genai_sdk):
    chunks = [FakeGenerateContentResponse(text="Once "), FakeGenerateContentResponse(text="upon a time.")]
    models_api = FakeModelsAPI(generate_content_stream_result=chunks)
    provider = _provider(models_api)

    received = list(provider.stream(GenerateRequest(prompt="Tell me a story")))

    assert "".join(chunk.text for chunk in received) == "Once upon a time."
    assert all(chunk.profile_id == "flash-38" for chunk in received)
