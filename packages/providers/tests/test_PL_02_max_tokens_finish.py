"""PL-02 (PRD 6.4) output-token exhaustion: a reply that stops because it hit its output cap (Gemini
`finish_reason == "MAX_TOKENS"`, OpenAI-compatible `finish_reason == "length"`) is never an ordinary reply.

Incident (first LIVE run of bank case B-007): the Director's call carried a 4096-token cap, the model's thinking
tokens used all of it, Gemini returned MAX_TOKENS with no text, and nothing in `google_adapter` knew the finish
reason. The empty reply failed schema validation, the repair failed too, the Router gave up with no adapter error
behind it, and `vertex_smoke.classify` printed "unknown". The same gap exists in `openai_compat_adapter`, which
returns a `length` completion as a plain (cut-off) success.

API the builder implements, pinned here:

  * `tilo_providers.errors.OutputTruncatedError(ProviderError)`, built as
    `OutputTruncatedError(message, *, output_tokens=None, thinking_tokens=None)` and exposing those two counts as
    attributes. It is NOT a SafetyError, RequestError, QuotaError or RetryableError (retrying the same request with
    the same cap would burn the same tokens again). Its message names both counts and never quotes the reply text
    (a reply can carry personal data: `intake.py` logs only the error class for the same reason).
      - `output_tokens`: the visible output the model produced (Gemini `candidates_token_count`, OpenAI-compatible
        `completion_tokens`); a count the provider left out (None) is 0 when usage is present (the existing
        `usage` convention), and None when the response has no usage at all.
      - `thinking_tokens`: Gemini `thoughts_token_count`, same None rule; None for an adapter with no such count.
  * `GoogleModelProvider.generate()` and `.stream()` raise it for a MAX_TOKENS candidate, whether the text is
    empty, missing or cut off, and whether `finish_reason` is the plain string or the SDK's str-enum member.
  * `OpenAICompatModelProvider.generate()` and `.stream()` raise it for `finish_reason == "length"`.
  * The Router gives it no same-profile retry and no schema repair; it may fall back to the next profile or stop,
    but whatever it raises has the error in its `__cause__` chain, so `vertex_smoke.classify` returns "truncated".

Config (PRD 6.4 role fields, contracts/providers.schema.json `role.max_output_tokens`): a role whose thinking is
`high` or `medium` states its `max_output_tokens` in every shipped models file, large enough for thinking plus
output. The Router's own default for a role with no cap is 1024 (BQ-63), and the incident's 4096 was already too
small, so the floor below is above 4096. 8192 (the next power of two) is an ASSUMPTION of this test, not a Gemini
limit: the repo states no model output limit (the schema sets no maximum; `HARD_MAX_OUTPUT_TOKENS` in
vertex_smoke.py is the smoke test's own 256-token spend guard and does not apply). The ceiling asserted is the
profile's own `context`, which the config does state.

Nothing here touches a network: the Gen AI SDK is faked at the `sys.modules` boundary, the OpenAI-compatible
endpoint with `httpx.MockTransport`, and the Router runs on scripted providers.
"""

from __future__ import annotations

import enum
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from _fake_genai_sdk import FakeCandidate, FakeClient, FakeGenerateContentResponse, FakeModelsAPI
from conftest import REPO_ROOT, ScriptedCall, ScriptedModelProvider
from tilo_contracts import ProvidersProfile
from tilo_providers.config import load_providers_config
from tilo_providers.errors import ProviderError, QuotaError, RequestError, RetryableError, SafetyError
from tilo_providers.interfaces import GenerateRequest

REPLY_TEXT = "SECRET-REPLY-BODY-MARKER"  # must never be echoed by an error message
CUT_OFF_JSON = '{"goal": "Summarise the ' + REPLY_TEXT  # what a truncated structured reply looks like
OUTPUT, THINKING = 225, 3871  # distinctive, so a message that names them is unmistakable (they sum to the 4096 cap)
MIN_THINKING_CAP = 8192  # assumption stated in the module docstring
ROUTER_DEFAULT_CAP = 1024  # router.py `_start`: the cap a role with none gets (BQ-63)
MODELS_FILES = ("models.yaml", "models.gemini.yaml", "models.nim.yaml")  # every shipped file with thinking roles


class FinishReason(enum.StrEnum):  # the SDK's own enum is a str enum: the adapter must compare by value
    MAX_TOKENS = "MAX_TOKENS"
    STOP = "STOP"


# ---------------------------------------------------------------------------------------------------------------
# Google adapter
# ---------------------------------------------------------------------------------------------------------------


def _google(response: FakeGenerateContentResponse | list[FakeGenerateContentResponse]) -> Any:
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "adapter-test-model", "context": 1000, "caps": ["json", "thinking"]}
    )
    models = (
        FakeModelsAPI(generate_content_stream_result=response)
        if isinstance(response, list)
        else FakeModelsAPI(generate_content_result=response)
    )
    return GoogleModelProvider(
        profile=profile, profile_id="flash-38", project="demo-project", location="global", client=FakeClient(models)
    )


def _usage(candidates: int | None, thoughts: int | None, prompt: int = 694) -> SimpleNamespace:
    """Vertex usage metadata; a count it leaves out is None (not 0)."""
    total = prompt + (candidates or 0) + (thoughts or 0)
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=candidates,
        thoughts_token_count=thoughts,
        total_token_count=total,
        cached_content_token_count=None,
    )


def _response(
    text: str | None, usage: SimpleNamespace | None, finish: object = "MAX_TOKENS"
) -> FakeGenerateContentResponse:
    return FakeGenerateContentResponse(
        text=text,
        usage_metadata=usage,  # type: ignore[arg-type]  # a duck-typed usage (fields left out on purpose)
        candidates=[FakeCandidate(finish_reason=finish)],  # type: ignore[arg-type]
    )


# (id, text, usage, expected output_tokens, expected thinking_tokens): the shapes a MAX_TOKENS reply takes
TRUNCATED_SHAPES = [
    pytest.param(None, _usage(0, 4096), 0, 4096, id="no-text-thinking-used-the-whole-cap"),
    pytest.param("", _usage(0, 4096), 0, 4096, id="empty-text-thinking-used-the-whole-cap"),
    pytest.param(None, _usage(None, 4096), 0, 4096, id="no-text-vertex-left-the-candidate-count-out"),
    pytest.param(CUT_OFF_JSON, _usage(OUTPUT, THINKING), OUTPUT, THINKING, id="cut-off-text-with-thinking"),
    pytest.param(CUT_OFF_JSON, _usage(4096, None), 4096, None, id="cut-off-text-vertex-left-thoughts-out"),
    pytest.param(None, None, None, None, id="no-usage-at-all"),
]


@pytest.mark.parametrize("finish", ["MAX_TOKENS", FinishReason.MAX_TOKENS], ids=["str", "sdk-enum"])
@pytest.mark.parametrize(("text", "usage", "output", "thinking"), TRUNCATED_SHAPES)
def test_PL_02_google_max_tokens_finish_raises_output_truncated_not_a_reply(
    fake_genai_sdk, text, usage, output, thinking, finish
):
    from tilo_providers.errors import OutputTruncatedError  # noqa: PLC0415

    provider = _google(_response(text, usage, finish))
    with pytest.raises(OutputTruncatedError) as raised:
        provider.generate(GenerateRequest(prompt="Draft a brief.", max_output_tokens=4096))
    error = raised.value
    assert isinstance(error, ProviderError)
    assert not isinstance(error, SafetyError | RequestError | QuotaError | RetryableError)
    assert (error.output_tokens, error.thinking_tokens) == (output, thinking)
    assert REPLY_TEXT not in str(error), "the error text must never quote the model's reply"
    if usage is not None and thinking:  # the message tells a person how the cap was spent
        assert str(thinking) in str(error)
    if usage is not None and output:
        assert str(output) in str(error)


def test_PL_02_google_max_tokens_message_names_both_counts_when_both_are_known(fake_genai_sdk):
    from tilo_providers.errors import OutputTruncatedError  # noqa: PLC0415

    provider = _google(_response(CUT_OFF_JSON, _usage(OUTPUT, THINKING)))
    with pytest.raises(OutputTruncatedError) as raised:
        provider.generate(GenerateRequest(prompt="Draft a brief.", max_output_tokens=4096))
    assert str(OUTPUT) in str(raised.value) and str(THINKING) in str(raised.value)


@pytest.mark.parametrize("finish", ["STOP", FinishReason.STOP, None])
def test_PL_02_google_a_finished_reply_is_not_truncated(fake_genai_sdk, finish):
    # guard: the new branch must not catch an ordinary finish (including a missing finish_reason)
    provider = _google(_response('{"goal": "ok"}', _usage(30, 400), finish))
    reply = provider.generate(GenerateRequest(prompt="Draft a brief.", max_output_tokens=4096))
    assert reply.text == '{"goal": "ok"}'
    assert reply.usage is not None and reply.usage["output_tokens"] == 430


def test_PL_02_google_stream_max_tokens_finish_raises_output_truncated(fake_genai_sdk):
    from tilo_providers.errors import OutputTruncatedError  # noqa: PLC0415

    chunks = [_response('{"goal": "Summ', None, finish=None), _response("", _usage(0, 4096), "MAX_TOKENS")]
    provider = _google(chunks)
    with pytest.raises(OutputTruncatedError) as raised:
        list(provider.stream(GenerateRequest(prompt="Draft a brief.", max_output_tokens=4096)))
    assert raised.value.thinking_tokens == 4096


# ---------------------------------------------------------------------------------------------------------------
# OpenAI-compatible adapter: `length` is the same condition
# ---------------------------------------------------------------------------------------------------------------

BASE_URL = "https://mock.openai-compat.example/v1"
KEY_ENV = "FAKE_MAX_TOKENS_API_KEY"


def _compat(handler: Any) -> Any:
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "openai_compat", "model": "org/some-model", "context": 128_000, "caps": ["json"]}
    )
    return OpenAICompatModelProvider(
        profile=profile,
        profile_id="compat-1",
        base_url=BASE_URL,
        api_key_env=KEY_ENV,
        transport=httpx.MockTransport(handler),
    )


def _completion(content: str | None, finish: str, completion_tokens: int = 4096) -> httpx.Response:
    body = {
        "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 694,
            "completion_tokens": completion_tokens,
            "total_tokens": 694 + completion_tokens,
        },
    }
    return httpx.Response(200, json=body)


@pytest.mark.parametrize("content", [None, "", CUT_OFF_JSON], ids=["no-content", "empty", "cut-off"])
def test_PL_02_openai_compat_length_finish_raises_output_truncated_not_a_reply(monkeypatch, content):
    from tilo_providers.errors import OutputTruncatedError  # noqa: PLC0415

    monkeypatch.setenv(KEY_ENV, "fake-test-key-do-not-use-1234567890")
    provider = _compat(lambda _request: _completion(content, "length"))
    with pytest.raises(OutputTruncatedError) as raised:
        provider.generate(GenerateRequest(prompt="Draft a brief.", max_output_tokens=4096))
    assert (raised.value.output_tokens, raised.value.thinking_tokens) == (4096, None)
    assert "4096" in str(raised.value) and REPLY_TEXT not in str(raised.value)


def test_PL_02_openai_compat_stop_finish_is_not_truncated(monkeypatch):
    # guard: an ordinary completion still comes back as a reply
    monkeypatch.setenv(KEY_ENV, "fake-test-key-do-not-use-1234567890")
    reply = _compat(lambda _request: _completion('{"goal": "ok"}', "stop", 12)).generate(
        GenerateRequest(prompt="Draft a brief.")
    )
    assert reply.text == '{"goal": "ok"}'


def test_PL_02_openai_compat_stream_length_finish_raises_output_truncated(monkeypatch):
    from tilo_providers.errors import OutputTruncatedError  # noqa: PLC0415

    monkeypatch.setenv(KEY_ENV, "fake-test-key-do-not-use-1234567890")
    sse = (
        'data: {"choices": [{"delta": {"content": "par"}}]}\n\n'
        'data: {"choices": [{"delta": {}, "finish_reason": "length"}]}\n\n'
        "data: [DONE]\n\n"
    )
    provider = _compat(lambda _request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse))
    with pytest.raises(OutputTruncatedError):
        list(provider.stream(GenerateRequest(prompt="Draft a brief.", max_output_tokens=4096)))


# ---------------------------------------------------------------------------------------------------------------
# Router and failure classification: never "unknown"
# ---------------------------------------------------------------------------------------------------------------


def _config(models_file: str = "models.yaml") -> Any:
    return load_providers_config(REPO_ROOT / "config" / models_file, REPO_ROOT / "config" / "prices.yaml")


def _router(config: Any, providers: dict[str, ScriptedModelProvider]) -> Any:
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


def _chain(error: BaseException) -> list[BaseException]:
    links: list[BaseException] = []
    while error is not None and error not in links:
        links.append(error)
        error = error.__cause__  # type: ignore[assignment]
    return links


def test_PL_02_router_gives_a_truncated_reply_no_same_profile_retry_and_a_classifiable_cause():
    from tilo_providers.errors import OutputTruncatedError  # noqa: PLC0415
    from tilo_providers.router import RouterError  # noqa: PLC0415
    from tilo_providers.vertex_smoke import classify  # noqa: PLC0415

    config = _config()
    director = config.roles["director"]
    cut = OutputTruncatedError("PL-02: output cap reached", output_tokens=0, thinking_tokens=4096)
    providers = {
        profile: ScriptedModelProvider(profile, [ScriptedCall(outcome="error", error=cut)] * 3)
        for profile in config.profiles
    }
    schema = {"type": "object", "properties": {"goal": {"type": "string"}}, "required": ["goal"]}
    request = GenerateRequest(prompt="Draft a brief.", json_mode=True, response_schema=schema)
    with pytest.raises(RouterError) as raised:
        _router(config, providers).generate("director", request)
    for profile in {director.primary, director.fallback}:
        assert len(providers[profile].calls) <= 1, f"{profile}: a truncated reply is never retried or repaired"
    assert any(isinstance(link, OutputTruncatedError) for link in _chain(raised.value)), "the cause is kept"
    assert raised.value.attempts[-1].error_type == "OutputTruncatedError"
    assert classify(raised.value) == "truncated"  # the line the live run prints, instead of "unknown"


def test_PL_02_classify_names_a_truncated_cause_and_keeps_the_other_codes():
    from tilo_providers.errors import OutputTruncatedError, map_http_status  # noqa: PLC0415
    from tilo_providers.router import RouterExhaustedError  # noqa: PLC0415
    from tilo_providers.vertex_smoke import classify  # noqa: PLC0415

    def exhausted(cause: Exception | None) -> RouterExhaustedError:
        error = RouterExhaustedError("PL-03: role 'director' exhausted every candidate")
        error.__cause__ = cause
        return error

    assert classify(exhausted(OutputTruncatedError("cap reached", thinking_tokens=4096))) == "truncated"
    assert classify(exhausted(map_http_status(429, "slow down"))) == "quota"  # unchanged
    assert classify(exhausted(None)) == "unknown"  # a failure with no cause is still unknown


# ---------------------------------------------------------------------------------------------------------------
# Config: a thinking role states a cap that thinking plus output can fit in
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("models_file", MODELS_FILES)
def test_PL_02_roles_with_thinking_high_or_medium_declare_a_max_output_tokens_floor(models_file: str):
    config = _config(models_file)
    thinking_roles = {name: role for name, role in config.roles.items() if role.thinking in ("high", "medium")}
    assert {"director", "lead", "verifier"} <= set(thinking_roles), "the roles the incident names still think"
    for name, role in thinking_roles.items():
        where = f"{models_file}: role {name!r} (thinking {role.thinking})"
        assert role.max_output_tokens is not None, f"{where} sets no max_output_tokens"
        assert role.max_output_tokens >= MIN_THINKING_CAP, f"{where} has cap {role.max_output_tokens}"
        for profile in (role.primary, role.fallback):  # never above what the profile itself can hold
            if profile:
                assert role.max_output_tokens <= config.profiles[profile].context, f"{models_file}: {name!r}"


@pytest.mark.parametrize("models_file", MODELS_FILES)
def test_PL_02_a_thinking_role_never_falls_back_to_a_cap_below_the_floor_when_called_through_the_router(
    models_file: str,
):
    config = _config(models_file)
    for name, role in config.roles.items():
        if role.thinking not in ("high", "medium"):
            continue
        providers = {profile: ScriptedModelProvider(profile, [ScriptedCall(text="ok")]) for profile in config.profiles}
        _router(config, providers).generate(name, GenerateRequest(prompt="Do the work."))  # the caller names no cap
        sent = [call.max_output_tokens for provider in providers.values() for call in provider.calls]
        assert sent, f"{models_file}: no call reached a provider for role {name!r}"
        assert all(n is not None and n >= MIN_THINKING_CAP for n in sent), (
            f"{models_file}: role {name!r} went out with max_output_tokens={sent} "
            f"(the Router's default is {ROUTER_DEFAULT_CAP}); thinking tokens count against it"
        )
