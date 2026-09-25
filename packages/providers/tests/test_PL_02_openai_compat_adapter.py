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
    """PL-02 JSON mode: `GenerateRequest.json_mode` must reach the API call
    as `response_format: {"type": "json_object"}` -- not merely pass
    unmodified JSON text through, which a caller with no way to ask for JSON
    at all would also satisfy."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    payload = '{"ok": true, "count": 3}'
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": payload}, "finish_reason": "stop"}]}
        )

    provider = _provider(handler, profile=_profile(caps=["json"]))
    response = provider.generate(GenerateRequest(prompt="Reply with JSON.", json_mode=True))

    assert response.text == payload
    assert json.loads(response.text) == {"ok": True, "count": 3}
    body = json.loads(seen[0].content)
    assert body["response_format"] == {"type": "json_object"}


def test_PL_02_openai_compat_adapter_generate_structured_output_sends_a_json_schema(monkeypatch):
    """PL-02 structured output: `GenerateRequest.response_schema` must reach
    the API call as a `response_format: {"type": "json_schema", ...}` whose
    `json_schema.schema` is the caller's schema."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}, "finish_reason": "stop"}]},
        )

    provider = _provider(handler, profile=_profile(caps=["json"]))
    provider.generate(GenerateRequest(prompt="Reply with JSON.", response_schema=schema))

    body = json.loads(seen[0].content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == schema


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


def test_PL_02_openai_compat_adapter_maps_content_filter_to_safety_error(monkeypatch):
    """Review fix (correctness): errors.py claims "every adapter maps ...
    onto these four types", and the google adapter already raises
    SafetyError on a `prompt_feedback.block_reason` block. This adapter must
    map the OpenAI-compatible equivalent -- a `finish_reason: "content_filter"`
    completion -- the same way, in both generate() and stream(), instead of
    returning it as an ordinary (possibly empty/partial) GenerateResponse
    that a caller (the P0-06 router) would otherwise treat as a normal,
    successful, empty answer (honesty rule: never invent output the model
    did not produce)."""
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def generate_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": None}, "finish_reason": "content_filter"}]},
        )

    provider = _provider(generate_handler)
    with pytest.raises(provider_errors.SafetyError):
        provider.generate(GenerateRequest(prompt="something unsafe"))

    sse_body = (
        'data: {"choices": [{"delta": {"content": "par"}}]}\n\n'
        'data: {"choices": [{"delta": {}, "finish_reason": "content_filter"}]}\n\n'
        "data: [DONE]\n\n"
    )

    def stream_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body)

    stream_provider = _provider(stream_handler)
    with pytest.raises(provider_errors.SafetyError):
        list(stream_provider.stream(GenerateRequest(prompt="something unsafe")))


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


def test_PL_02_openai_compat_adapter_stream_sends_max_output_tokens(monkeypatch):
    """Review fix: `stream()` must forward `max_output_tokens` as `max_tokens`
    on the request body, the same as `generate()` already does."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="data: [DONE]\n\n")

    provider = _provider(handler)
    list(provider.stream(GenerateRequest(prompt="Say hi", max_output_tokens=64)))

    body = json.loads(seen[0].content)
    assert body["max_tokens"] == 64


def test_PL_02_openai_compat_adapter_stream_accumulates_a_streamed_tool_call(monkeypatch):
    """Review fix: streamed tool-call deltas (fragmented by `index`, with
    `arguments` split across chunks) must be accumulated and surfaced, not
    silently dropped."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    sse_body = (
        'data: {"choices": [{"delta": {"tool_calls": ['
        '{"index": 0, "id": "call_1", "function": {"name": "get_weather", "arguments": ""}}'
        "]}}]}\n\n"
        'data: {"choices": [{"delta": {"tool_calls": ['
        '{"index": 0, "function": {"arguments": "{\\"location\\": "}}'
        "]}}]}\n\n"
        'data: {"choices": [{"delta": {"tool_calls": ['
        '{"index": 0, "function": {"arguments": "\\"Boston\\"}"}}'
        "]}}]}\n\n"
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse_body)

    tool_schema = {
        "type": "function",
        "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {"location": {}}}},
    }
    provider = _provider(handler, profile=_profile(caps=["tools"]))
    chunks = list(provider.stream(GenerateRequest(prompt="Weather in Boston?", tools=[tool_schema])))

    assert chunks[-1].tool_calls == [{"name": "get_weather", "args": {"location": "Boston"}}]
    assert all(chunk.text is None for chunk in chunks), "no content deltas in this stream"


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


def test_PL_02_openai_compat_adapter_maps_a_string_error_field(monkeypatch):
    """Regression: `{"error": "<string>"}` (a valid, if informal, error
    shape) must not raise an unmapped AttributeError from calling `.get` on
    a string."""
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    provider = _provider(handler)
    with pytest.raises(provider_errors.RequestError) as excinfo:
        provider.generate(GenerateRequest(prompt="hi"))
    assert "bad request" in str(excinfo.value)


def test_PL_02_openai_compat_adapter_scrubs_the_api_key_from_error_bodies(monkeypatch):
    """A misbehaving/echoing proxy that reflects the Authorization header
    back in its error body must not leak the key into the raised error
    (PRD 16.1 rule 4)."""
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": f"rejected header 'Bearer {FAKE_KEY}'"}})

    provider = _provider(handler)
    with pytest.raises(provider_errors.RequestError) as excinfo:
        provider.generate(GenerateRequest(prompt="hi"))
    assert FAKE_KEY not in str(excinfo.value)
    assert "***" in str(excinfo.value)


@pytest.mark.parametrize("offset", [440, 460, 480, 490, 499])
def test_PL_02_openai_compat_adapter_scrubs_a_key_straddling_the_error_truncation(monkeypatch, offset):
    """Review fix (security): a long echoed body where the key crosses the
    500-character cut must not leak any prefix of the key (PRD 16.1 rule 4)."""
    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "x" * offset + FAKE_KEY + "y" * 600}})

    provider = _provider(handler)
    with pytest.raises(provider_errors.RequestError) as excinfo:
        provider.generate(GenerateRequest(prompt="hi"))
    text = str(excinfo.value)
    for length in range(8, len(FAKE_KEY) + 1):
        assert FAKE_KEY[:length] not in text, f"key prefix of {length} chars leaked at offset {offset}"


def test_PL_02_openai_compat_adapter_rejects_a_non_loopback_http_base_url(monkeypatch):
    """PL-02/PRD 16.1 rule 4: plain `http://` is only ever allowed for a
    loopback test server (`localhost`/`127.0.0.1`) -- any other host must be
    rejected at construction, before a client carrying the bearer key in
    cleartext could ever be built."""
    from tilo_providers.errors import ProviderError
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    with pytest.raises(ProviderError) as excinfo:
        OpenAICompatModelProvider(
            profile=_profile(),
            profile_id="compat-1",
            base_url="http://integrate.api.nvidia.com/v1",
            api_key_env=API_KEY_ENV,
        )
    assert "https" in str(excinfo.value).lower()


def test_PL_02_openai_compat_adapter_refuses_a_real_client_without_live(monkeypatch):
    """EFF-01: the LIVE=1 gate cannot live only in
    `tilo_providers.replay.RecordReplayProvider` -- direct construction with
    no injected `transport` and `LIVE` unset must refuse before any
    `httpx.Client` (real network client) exists."""
    from tilo_providers.errors import ProviderError
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    monkeypatch.delenv("LIVE", raising=False)

    with pytest.raises(ProviderError) as excinfo:
        OpenAICompatModelProvider(profile=_profile(), profile_id="compat-1", base_url=BASE_URL, api_key_env=API_KEY_ENV)
    assert "LIVE" in str(excinfo.value)


def test_PL_02_openai_compat_adapter_rejects_a_dirty_api_key_naming_only_the_variable(monkeypatch):
    """Ticket P0-05 review fix (security): an env value with a stray
    control/whitespace character (e.g. a trailing CR pasted on Windows)
    must be rejected at construction time, before it can ever reach an HTTP
    header -- and the error must name only the variable, never the value."""
    from tilo_providers.errors import ProviderError
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider

    dirty_key = f"{FAKE_KEY}\r"
    monkeypatch.setenv(API_KEY_ENV, dirty_key)

    with pytest.raises(ProviderError) as excinfo:
        OpenAICompatModelProvider(profile=_profile(), profile_id="compat-1", base_url=BASE_URL, api_key_env=API_KEY_ENV)

    assert API_KEY_ENV in str(excinfo.value)
    assert FAKE_KEY not in str(excinfo.value)
    assert dirty_key not in str(excinfo.value)


def test_PL_02_openai_compat_adapter_post_exception_never_leaks_the_api_key(monkeypatch):
    """Defense in depth for the same failure (see the construction-time
    check above): if a header value that breaks HTTP framing ever reached
    the wire regardless, `_post`'s own exception handling must still not
    surface it. `httpx.MockTransport` never reaches h11 (the review's own
    finding), so this needs a real transport talking to a real loopback
    listener -- allowed by conftest.py's `block_non_local_sockets`. This is
    the one test in this file that builds a real (if loopback-only)
    `httpx.Client` rather than injecting `transport=`, so it must say
    `LIVE=1` itself (EFF-01: the adapter refuses to build a real client
    without it)."""
    import socket
    import threading
    import traceback

    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)
    monkeypatch.setenv("LIVE", "1")
    dirty_key = f"{FAKE_KEY}\r"

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def _accept_loop() -> None:
        try:
            while True:
                conn, _ = server.accept()
                conn.close()
        except OSError:
            pass

    thread = threading.Thread(target=_accept_loop, daemon=True)
    thread.start()
    try:
        from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider

        provider = OpenAICompatModelProvider(
            profile=_profile(), profile_id="compat-1", base_url=f"http://127.0.0.1:{port}/v1", api_key_env=API_KEY_ENV
        )
        # Simulate a bad value reaching the wire despite the constructor's
        # own check above -- exactly the h11 "Illegal header value" failure
        # the review reported, exercised against a real transport.
        provider._client.headers["authorization"] = f"Bearer {dirty_key}"  # noqa: SLF001

        from tilo_providers import errors as provider_errors  # noqa: PLC0415

        with pytest.raises(provider_errors.ProviderError) as excinfo:
            provider.generate(GenerateRequest(prompt="hi"))

        formatted = "".join(traceback.format_exception(type(excinfo.value), excinfo.value, excinfo.value.__traceback__))
        assert FAKE_KEY not in str(excinfo.value)
        assert FAKE_KEY not in formatted
    finally:
        server.close()


def test_PL_02_openai_compat_adapter_generate_maps_a_malformed_2xx_body(monkeypatch):
    """A 2xx response whose body is not valid JSON must surface as a
    ProviderError, not a raw JSONDecodeError."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    provider = _provider(handler)

    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    with pytest.raises(provider_errors.ProviderError):
        provider.generate(GenerateRequest(prompt="hi"))


def test_PL_02_openai_compat_adapter_generate_maps_a_2xx_body_missing_choices(monkeypatch):
    """A 2xx response with valid JSON but no usable "choices" must surface
    as a ProviderError, not a raw KeyError/IndexError."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    provider = _provider(handler)

    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    with pytest.raises(provider_errors.ProviderError):
        provider.generate(GenerateRequest(prompt="hi"))


def test_PL_02_openai_compat_adapter_embeddings_maps_a_2xx_body_missing_data(monkeypatch):
    """A 2xx embeddings response missing "data"/"embedding" must surface as
    a ProviderError, not a raw KeyError."""
    monkeypatch.setenv(API_KEY_ENV, FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{}]})

    provider = _provider(handler)

    from tilo_providers import errors as provider_errors  # noqa: PLC0415

    with pytest.raises(provider_errors.ProviderError):
        provider.embed(["hi"])
