"""PL-02 / FR-MTR-01: a truncated call was billed, input as well as output, so `OutputTruncatedError` carries the
provider's own input-token count (`input_tokens`, Gemini `prompt_token_count`, OpenAI-compatible `prompt_tokens`), None
when the response reported no usage. The Router and the live meter bill the call from it. Fakes only, no network."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from _fake_genai_sdk import FakeCandidate, FakeClient, FakeGenerateContentResponse, FakeModelsAPI
from tilo_contracts import ProvidersProfile
from tilo_providers.errors import OutputTruncatedError
from tilo_providers.interfaces import GenerateRequest

KEY_ENV = "FAKE_TRUNCATED_INPUT_API_KEY"


def test_PL_02_the_error_carries_input_tokens_and_defaults_to_none() -> None:
    assert OutputTruncatedError("cut").input_tokens is None
    assert OutputTruncatedError("cut", output_tokens=1, thinking_tokens=2, input_tokens=3).input_tokens == 3


def _google(usage: SimpleNamespace | None) -> object:
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "adapter-test-model", "context": 1000, "caps": ["json", "thinking"]}
    )
    response = FakeGenerateContentResponse(
        text=None,
        usage_metadata=usage,  # type: ignore[arg-type]
        candidates=[FakeCandidate(finish_reason="MAX_TOKENS")],  # type: ignore[arg-type]
    )
    return GoogleModelProvider(
        profile=profile,
        profile_id="flash-38",
        project="demo-project",
        location="global",
        client=FakeClient(FakeModelsAPI(generate_content_result=response)),
    )


def test_PL_02_google_truncation_reports_the_prompt_token_count(fake_genai_sdk) -> None:
    usage = SimpleNamespace(
        prompt_token_count=694,
        candidates_token_count=None,
        thoughts_token_count=1024,
        total_token_count=1718,
        cached_content_token_count=None,
    )

    with pytest.raises(OutputTruncatedError) as raised:
        _google(usage).generate(GenerateRequest(prompt="Draft.", max_output_tokens=1024))  # type: ignore[attr-defined]

    error = raised.value
    assert (error.input_tokens, error.output_tokens, error.thinking_tokens) == (694, 0, 1024)


def test_PL_02_google_truncation_with_no_usage_has_no_input_tokens(fake_genai_sdk) -> None:
    with pytest.raises(OutputTruncatedError) as raised:
        _google(None).generate(GenerateRequest(prompt="Draft.", max_output_tokens=1024))  # type: ignore[attr-defined]

    assert raised.value.input_tokens is None


def _compat(body: dict) -> object:
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "openai_compat", "model": "org/some-model", "context": 128_000, "caps": ["json"]}
    )
    return OpenAICompatModelProvider(
        profile=profile,
        profile_id="compat-1",
        base_url="https://mock.openai-compat.example/v1",
        api_key_env=KEY_ENV,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)),
    )


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_tokens": 694, "completion_tokens": 4096}, 694),
        ({"completion_tokens": 4096}, None),
        (None, None),
    ],
    ids=["with-prompt-tokens", "no-prompt-tokens", "no-usage"],
)
def test_PL_02_openai_compat_truncation_reports_prompt_tokens_where_present(monkeypatch, usage, expected) -> None:
    monkeypatch.setenv(KEY_ENV, "fake-test-key-do-not-use-1234567890")
    body: dict = {"choices": [{"message": {"role": "assistant", "content": None}, "finish_reason": "length"}]}
    if usage is not None:
        body["usage"] = usage

    with pytest.raises(OutputTruncatedError) as raised:
        _compat(body).generate(GenerateRequest(prompt="Draft.", max_output_tokens=4096))  # type: ignore[attr-defined]

    assert raised.value.input_tokens == expected
