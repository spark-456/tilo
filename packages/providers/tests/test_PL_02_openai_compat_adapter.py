"""PL-02 (PRD 6.4): "a generic OpenAI-compatible adapter... passes against a
local mock". Ticket P0-05 item 2: base_url and api_key_env from the profile
config, chat completions (incl. streaming SSE, tool calls, JSON mode),
embeddings, usage tokens, error mapping; works for any OpenAI-compatible
endpoint including NVIDIA NIM.

Public interface under test: `ModelProvider.generate/stream/embed` (PRD 6.4)
via `tilo_providers.openai_compat_adapter.OpenAICompatModelProvider`. No
real socket is opened: `httpx.MockTransport` intercepts every request
in-process (httpx is already a workspace dev dependency, BSD-3-Clause,
`docs/licences.md`); `conftest.py`'s `block_non_local_sockets` guards the
rest of the suite.

Constructor assumption (see report): `OpenAICompatModelProvider(profile,
profile_id, base_url, api_key_env, transport=None)`. `base_url` and
`api_key_env` are taken as direct constructor arguments here, not read off
`ProvidersProfile` -- `contracts/providers.schema.json`'s `$defs.profile`
has `additionalProperties: false` and no such fields today (needs contract
change, see `test_PL_02_nvidia_nim_example_profiles.py` and the report); the
adapter itself does not depend on that contract. `transport` is an injected
`httpx.BaseTransport`, used only by tests -- production code would leave it
unset and let `httpx.Client` open a real connection under `LIVE=1`.

Interface assumption shared with the google adapter test file: `tool_calls`
and `usage` are optional fields this ticket adds to `GenerateResponse`.
JSON mode has no explicit toggle on `GenerateRequest` (P0-04 kept it thin),
so it is tested as response-fidelity (valid JSON text passed through
unmodified), the same choice made for the google adapter -- logged as an
ambiguity in the report.
"""

from __future__ import annotations

import json

import httpx
import pytest
from tilo_contracts import ProvidersProfile
from tilo_providers.interfaces import GenerateRequest, ModelProvider

BASE_URL = "https://mock.openai-compat.example/v1"
API_KEY_ENV = "FAKE_OPENAI_COMPAT_API_KEY"
FAKE_KEY = "fake-test-key-do-not-use-1234567890"  # assembled here at runtime, never a real secret


def _profile(**overrides: object) -> ProvidersProfile:
    fields: dict[str, object] = {
        "provider": "openai_compat",
        "model": "org/some-model",
        "context": 128_000,
        "caps": ["json", "tools"],
    }
    fields.update(overrides)
    return ProvidersProfile.model_validate(fields)


def _provider(handler, *, profile: ProvidersProfile | None = None, profile_id: str = "compat-1"):
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    return OpenAICompatModelProvider(
        profile=profile or _profile(),
        profile_id=profile_id,
        base_url=BASE_URL,
        api_key_env=API_KEY_ENV,
        transport=httpx.MockTransport(handler),
    )


def test_PL_02_openai_compat_adapter_conforms_to_model_provider(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("not called")

    provider = _provider(handler)
    assert isinstance(provider, ModelProvider)


def test_PL_02_openai_compat_adapter_generate_chat_completion(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        assert body["model"] == "org/some-model", "PL-01: the profile's model id, never hardcoded"
        assert body["messages"][-1] == {"role": "user", "content": "Say hi"}
        assert body["messages"][0] == {"role": "system", "content": "Be terse."}
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            },
        )

    provider = _provider(handler)
    response = provider.generate(GenerateRequest(prompt="Say hi", system="Be terse."))

    assert response.text == "hi"
    assert response.profile_id == "compat-1"
    assert seen[0].url.path.endswith("/chat/completions")
    assert seen[0].headers["authorization"] == f"Bearer {FAKE_KEY}"


def test_PL_02_openai_compat_adapter_generate_json_mode_round_trips_valid_json(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    payload = '{"ok": true, "count": 3}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": payload}, "finish_reason": "stop"}]}
        )

    provider = _provider(handler, profile=_profile(caps=["json"]))
    response = provider.generate(GenerateRequest(prompt="Reply with JSON."))

    assert response.text == payload
    assert json.loads(response.text) == {"ok": True, "count": 3}


def test_PL_02_openai_compat_adapter_generate_maps_a_tool_call(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    tool_schema = {
        "type": "function",
        "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"location": {}}}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["tools"] == [tool_schema], "PL-02: the request's tools must reach the API call"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "get_weather", "arguments": '{"location": "Boston"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    provider = _provider(handler, profile=_profile(caps=["tools"]))
    response = provider.generate(GenerateRequest(prompt="Weather in Boston?", tools=[tool_schema]))

    assert response.tool_calls == [{"name": "get_weather", "args": {"location": "Boston"}}]


def test_PL_02_openai_compat_adapter_stream_sse_concatenates_to_the_full_text(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    sse_body = (
        'data: {"choices": [{"delta": {"content": "Hel"}}]}\n\n'
        'data: {"choices": [{"delta": {"content": "lo"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body)

    provider = _provider(handler)
    chunks = list(provider.stream(GenerateRequest(prompt="Say hello")))

    assert "".join(chunk.text for chunk in chunks) == "Hello"


def test_PL_02_openai_compat_adapter_embeddings(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        body = json.loads(request.content)
        assert body["input"] == ["hello world"]
        return httpx.Response(
            200,
            json={
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"prompt_tokens": 3, "total_tokens": 3},
            },
        )

    provider = _provider(handler)
    result = provider.embed({"input": ["hello world"]})

    assert result["vectors"] == [[0.1, 0.2, 0.3]]
    assert result["usage"]["total_tokens"] == 3


@pytest.mark.parametrize(
    ("status_code", "expected_error_name"),
    [(429, "QuotaError"), (500, "RetryableError"), (503, "RetryableError"), (400, "RequestError")],
    ids=["429-quota", "500-retryable", "503-retryable", "400-request"],
)
def test_PL_02_openai_compat_adapter_maps_http_errors(monkeypatch, status_code, expected_error_name):
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    expected_error = getattr(provider_errors, expected_error_name)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"message": "boom"}})

    provider = _provider(handler)
    with pytest.raises(expected_error):
        provider.generate(GenerateRequest(prompt="hi"))


def test_PL_02_openai_compat_adapter_maps_timeout_to_retryable_error(monkeypatch):
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    provider = _provider(handler)
    with pytest.raises(provider_errors.RetryableError):
        provider.generate(GenerateRequest(prompt="hi"))
