"""EFF-04a (PRD 6.6, ADR-0022): the provider layer reports cached input tokens, and keeps each role's prompt
prefix stable. Fixtures, fakes and recordings only: no network, the live switch stays off.

Rules under test (ADR-0022 decision 6 and 7):
  - `usage["cached_tokens"]` is set only when the provider reported a whole number between 0 and `input_tokens`;
    otherwise the key is left out (unknown, never 0, never None), so EV-16 can never reject an event;
  - Google: a present `usage_metadata` whose cached count is None is a reported 0 (the API leaves a zero out);
  - an old recording has no key and replays as unknown;
  - `RouterAttempt.tokens_cached` is None for unknown;
  - stable prefix: system prompt, tool definitions, response schema, then the per-call text, and the static parts
    are byte-for-byte the same on two calls for the same role.
"""

from __future__ import annotations

import json
import string
import types as pytypes
from pathlib import Path
from typing import Any

import httpx
import pytest
from _fake_genai_sdk import FakeClient, FakeGenerateContentResponse, FakeModelsAPI, FakeUsageMetadata
from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    cascade_models_config,
    prices_config_for,
    write_providers_config,
)
from tilo_contracts import ProvidersProfile
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.prompts import DEFAULT_PROMPTS_ROOT, load_prompt

_MISSING = object()


# ---------------------------------------------------------------------------------------------- google


def _google(client: Any = None):
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "adapter-test-model", "context": 1000, "caps": ["json", "tools"]}
    )
    client = client or pytypes.SimpleNamespace(models=None)  # `_map_response` never touches the client
    return GoogleModelProvider(
        profile=profile, profile_id="g", project="demo-project", location="global", client=client
    )


def _gemini_response(cached: Any = _MISSING, prompt: int = 3300, with_usage: bool = True) -> Any:
    usage = None
    if with_usage:
        fields: dict[str, Any] = {
            "prompt_token_count": prompt,
            "candidates_token_count": 40,
            "total_token_count": prompt + 40,
            "thoughts_token_count": None,
        }
        if cached is not _MISSING:
            fields["cached_content_token_count"] = cached
        usage = pytypes.SimpleNamespace(**fields)
    return pytypes.SimpleNamespace(
        text="hi", function_calls=None, prompt_feedback=None, candidates=[], usage_metadata=usage
    )


def test_EFF_04_google_maps_cached_content_token_count():
    usage = _google()._map_response(_gemini_response(cached=2048)).usage
    assert usage == {"input_tokens": 3300, "output_tokens": 40, "total_tokens": 3340, "cached_tokens": 2048}


def test_EFF_04_google_usage_present_but_count_none_reports_a_known_zero():
    # the API leaves a zero count out: with usage_metadata present, that is a miss, not "unknown"
    usage = _google()._map_response(_gemini_response(cached=None)).usage
    assert usage is not None
    assert usage["cached_tokens"] == 0


def test_EFF_04_google_without_usage_metadata_has_no_usage_at_all():
    assert _google()._map_response(_gemini_response(with_usage=False)).usage is None


def test_EFF_04_google_an_object_that_carries_no_cached_field_reports_unknown():
    usage = _google()._map_response(_gemini_response()).usage
    assert usage is not None
    assert "cached_tokens" not in usage


@pytest.mark.parametrize("bad", [3301, 10**9, -1, True, 12.5, "2048"])
def test_EFF_04_google_never_reports_a_count_that_is_not_a_whole_number_within_input_tokens(bad):
    usage = _google()._map_response(_gemini_response(cached=bad, prompt=3300)).usage
    assert usage is not None
    assert "cached_tokens" not in usage, "left out, so EV-16 can never refuse the event"


def test_EFF_04_google_a_count_equal_to_input_tokens_is_kept():
    usage = _google()._map_response(_gemini_response(cached=3300, prompt=3300)).usage
    assert usage is not None
    assert usage["cached_tokens"] == 3300


def test_EFF_04_google_stream_reports_the_count_from_the_chunk_that_carries_usage(fake_genai_sdk):
    usage = FakeUsageMetadata(prompt_token_count=10, candidates_token_count=2, total_token_count=12)
    usage.cached_content_token_count = 4  # type: ignore[attr-defined]
    chunks = [
        FakeGenerateContentResponse(text="a"),
        FakeGenerateContentResponse(text="b", usage_metadata=usage),
    ]
    provider = _google(FakeClient(FakeModelsAPI(generate_content_stream_result=chunks)))
    got = list(provider.stream(GenerateRequest(prompt="x")))
    assert got[0].usage is None
    assert got[1].usage is not None
    assert got[1].usage["cached_tokens"] == 4


# ---------------------------------------------------------------------------------------------- openai-compat

_KEY_ENV = "FAKE_OPENAI_COMPAT_API_KEY_EFF04"
_BASE_URL = "https://mock.openai-compat.example/v1"


def _compat(monkeypatch: pytest.MonkeyPatch, handler):
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    monkeypatch.setenv(_KEY_ENV, "fake-" + "test-key-" + "1234567890")  # assembled at runtime
    profile = ProvidersProfile.model_validate(
        {"provider": "openai_compat", "model": "org/some-model", "context": 128_000, "caps": ["json", "tools"]}
    )
    return OpenAICompatModelProvider(
        profile=profile,
        profile_id="c",
        base_url=_BASE_URL,
        api_key_env=_KEY_ENV,
        transport=httpx.MockTransport(handler),
    )


def _completion(usage: Any) -> httpx.Response:
    body: dict[str, Any] = {"choices": [{"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}]}
    if usage is not _MISSING:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def _compat_usage(monkeypatch: pytest.MonkeyPatch, usage: Any) -> dict[str, int] | None:
    provider = _compat(monkeypatch, lambda request: _completion(usage))
    return provider.generate(GenerateRequest(prompt="x")).usage


def _raw(details: Any = _MISSING, prompt: int = 100) -> dict[str, Any]:
    raw: dict[str, Any] = {"prompt_tokens": prompt, "completion_tokens": 5, "total_tokens": prompt + 5}
    if details is not _MISSING:
        raw["prompt_tokens_details"] = details
    return raw


def test_EFF_04_openai_compat_maps_prompt_tokens_details_cached_tokens(monkeypatch):
    usage = _compat_usage(monkeypatch, _raw({"cached_tokens": 64}))
    assert usage == {"input_tokens": 100, "output_tokens": 5, "total_tokens": 105, "cached_tokens": 64}


def test_EFF_04_openai_compat_a_reported_zero_is_a_known_miss(monkeypatch):
    usage = _compat_usage(monkeypatch, _raw({"cached_tokens": 0}))
    assert usage is not None
    assert usage["cached_tokens"] == 0


@pytest.mark.parametrize(
    "details",
    [_MISSING, None, {}, {"cached_tokens": None}, {"cached_tokens": 101}, {"cached_tokens": -1}]
    + [{"cached_tokens": True}, {"cached_tokens": 1.5}, {"cached_tokens": "64"}, "oops", [64]],
)
def test_EFF_04_openai_compat_leaves_the_key_out_unless_a_whole_number_within_input_tokens(monkeypatch, details):
    usage = _compat_usage(monkeypatch, _raw(details))
    assert usage is not None
    assert usage == {"input_tokens": 100, "output_tokens": 5, "total_tokens": 105}


def test_EFF_04_openai_compat_a_count_equal_to_input_tokens_is_kept(monkeypatch):
    usage = _compat_usage(monkeypatch, _raw({"cached_tokens": 100}))
    assert usage is not None
    assert usage["cached_tokens"] == 100


def test_EFF_04_openai_compat_without_a_usage_object_has_no_usage(monkeypatch):
    assert _compat_usage(monkeypatch, _MISSING) is None


# ---------------------------------------------------------------------------------------------- fake and replay


def test_EFF_04_fake_provider_leaves_usage_out_by_default_and_serves_a_given_dict():
    from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415

    request = GenerateRequest(prompt="x")
    assert FakeModelProvider().generate(request).usage is None, "unknown, as before"
    given = {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55, "cached_tokens": 30}
    provider = FakeModelProvider(usage=given)
    assert provider.generate(request).usage == given
    assert next(iter(provider.stream(request))).usage == given


def _replayer(tmp_path: Path):
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    def no_live():
        raise AssertionError("EFF-01: a replay must never build a live provider")

    return RecordReplayProvider(role="director", profile_id="large", live_factory=no_live, fixtures_dir=tmp_path)


def _write_recording(tmp_path: Path, request: GenerateRequest, usage: dict[str, int] | None) -> None:
    from tilo_providers.replay import recording_key  # noqa: PLC0415

    key = recording_key("director", "large", request)
    response: dict[str, Any] = {"text": "hi", "profile_id": "large"}
    if usage is not None:
        response["usage"] = usage
    path = tmp_path / "model-recordings" / "director" / f"{key}.json"
    path.parent.mkdir(parents=True)
    payload = {"role": "director", "profile": "large", "key": key, "response": response}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_EFF_04_an_old_recording_replays_as_unknown(tmp_path):
    request = GenerateRequest(prompt="old")
    _write_recording(tmp_path, request, {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4})
    usage = _replayer(tmp_path).generate(request).usage
    assert usage == {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}
    assert "cached_tokens" not in usage, "not 0 and not None: the key is absent"


def test_EFF_04_an_old_recording_with_no_usage_at_all_still_replays_with_none(tmp_path):
    request = GenerateRequest(prompt="older")
    _write_recording(tmp_path, request, None)
    assert _replayer(tmp_path).generate(request).usage is None


def test_EFF_04_a_new_recording_replays_the_count_as_recorded(tmp_path):
    request = GenerateRequest(prompt="new")
    recorded = {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4, "cached_tokens": 2}
    _write_recording(tmp_path, request, recorded)
    assert _replayer(tmp_path).generate(request).usage == recorded


# ---------------------------------------------------------------------------------------------- router


def _router(tmp_path: Path, providers: dict[str, ScriptedModelProvider]):
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    models, prices = write_providers_config(
        tmp_path,
        cascade_models_config(),
        prices_config_for({"cheap": (0.1, 0.2), "mid": (0.5, 1.0), "rich": (2.0, 4.0)}),
    )
    return Router(load_providers_config(models, prices), provider_for_profile=providers.__getitem__)


def _usage(**extra: int) -> dict[str, int]:
    return {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110, **extra}


def test_EFF_04_router_attempt_defaults_to_unknown():
    from tilo_providers.router import RouterAttempt  # noqa: PLC0415

    assert RouterAttempt(profile_id="p", provider="fake", outcome="ok").tokens_cached is None


def test_EFF_04_router_fills_tokens_cached_from_usage(tmp_path):
    cheap = ScriptedModelProvider("cheap", [ScriptedCall(usage=_usage(cached_tokens=64))])
    router = _router(tmp_path, {"cheap": cheap})
    attempt = router.generate("analyst", GenerateRequest(prompt="x")).attempts[0]
    assert (attempt.tokens_in, attempt.tokens_out, attempt.tokens_cached) == (100, 10, 64)


def test_EFF_04_router_keeps_a_reported_zero_and_reads_a_missing_key_as_unknown(tmp_path):
    cheap = ScriptedModelProvider(
        "cheap", [ScriptedCall(usage=_usage(cached_tokens=0)), ScriptedCall(usage=_usage()), ScriptedCall(usage=None)]
    )
    router = _router(tmp_path, {"cheap": cheap})
    cached = [router.generate("analyst", GenerateRequest(prompt="x")).attempts[0].tokens_cached for _ in range(3)]
    assert cached == [0, None, None]


def test_EFF_04_router_stream_fills_tokens_cached_from_the_chunk_that_reports_it(tmp_path):
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.fake import FakeModelProvider  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    fake = FakeModelProvider(usage=_usage(cached_tokens=7))

    models, prices = write_providers_config(
        tmp_path, cascade_models_config(), prices_config_for({"cheap": (0.1, 0.2), "mid": (0.5, 1.0), "rich": (2, 4)})
    )
    router = Router(load_providers_config(models, prices), provider_for_profile=lambda _profile: fake)
    run = router.stream("analyst", GenerateRequest(prompt="x"))
    list(run)
    assert run.attempts[0].tokens_cached == 7


# ---------------------------------------------------------------------------------------------- stable prefix

_SYSTEM = "You are the Specialist. Answer in JSON."
_TOOLS = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}


def _static(request: GenerateRequest) -> str:
    return json.dumps([request.system, request.tools, request.response_schema], sort_keys=False)


def test_EFF_04_openai_compat_sends_tools_and_schema_ahead_of_the_per_call_text(monkeypatch):
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        return _completion(_MISSING)

    provider = _compat(monkeypatch, handler)
    for text in ("first question", "second, different question"):
        provider.generate(
            GenerateRequest(prompt=text, system=_SYSTEM, tools=_TOOLS, response_schema=_SCHEMA, max_output_tokens=50)
        )

    keys = [list(json.loads(body)) for body in bodies]
    for order in keys:
        assert order.index("tools") < order.index("response_format") < order.index("messages")
    first, second = (json.loads(body) for body in bodies)
    assert [m["role"] for m in first["messages"]] == ["system", "user"], "system prompt before the per-call text"
    assert first["messages"][0] == second["messages"][0]
    for key in ("model", "tools", "response_format"):
        assert json.dumps(first[key]) == json.dumps(second[key]), f"{key} is byte-identical across calls"
    assert first["messages"][1] != second["messages"][1]


def test_EFF_04_google_sends_system_tools_and_schema_in_that_order_ahead_of_the_per_call_text(fake_genai_sdk):
    api = FakeModelsAPI(generate_content_result=FakeGenerateContentResponse(text="{}"))
    provider = _google(FakeClient(api))
    for text in ("first question", "second, different question"):
        provider.generate(GenerateRequest(prompt=text, system=_SYSTEM, tools=_TOOLS, response_schema=_SCHEMA))

    first, second = api.calls
    order = list(vars(first["config"]))
    assert order.index("system_instruction") < order.index("tools") < order.index("response_json_schema")
    for key in ("system_instruction", "tools", "response_json_schema"):
        assert json.dumps(getattr(first["config"], key)) == json.dumps(getattr(second["config"], key))
    assert first["contents"] != second["contents"], "only the per-call text differs"


def test_EFF_04_the_router_passes_each_roles_static_parts_through_byte_for_byte(tmp_path, providers_config):
    from tilo_providers.router import Router  # noqa: PLC0415

    for role in providers_config.models.roles:
        providers = {
            profile: ScriptedModelProvider(profile, [ScriptedCall(text='{"answer": "x"}') for _ in range(2)])
            for profile in providers_config.models.profiles
        }
        router = Router(providers_config, provider_for_profile=providers.__getitem__)
        for text in ("one question", "another, longer question about something else"):
            router.generate(role, GenerateRequest(prompt=text, system=_SYSTEM, tools=_TOOLS, response_schema=_SCHEMA))
        sent = [call for provider in providers.values() for call in provider.calls]
        assert len(sent) == 2, role
        assert _static(sent[0]) == _static(sent[1]), f"role {role!r}: static parts must not change between calls"
        assert sent[0].prompt != sent[1].prompt


# Placeholders a `*_system.md` template may take: values that are the same on every call (a fixed list). A
# per-call value belongs in the task template, after the static prefix.
# `intents` and `routes` (assistant/route_system.md, PPL-11b) are the closed menus read once from config/assistant.yaml:
# the same on every call of a process, so the prefix stays byte-stable and cacheable.
# `gaps` and `services` (director/brief_system.md, FR-INT-15) are read once from config/capability_gaps.yaml in the
# same way.
_STATIC_PLACEHOLDERS = {"categories", "gaps", "intents", "routes", "services"}


def _system_templates() -> list[Path]:
    return sorted(DEFAULT_PROMPTS_ROOT.glob("*/*_system.md"))


def test_EFF_04_there_are_system_templates_to_check():
    assert len(_system_templates()) >= 5


@pytest.mark.parametrize("path", _system_templates(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_EFF_04_a_system_template_has_only_static_placeholders_and_renders_byte_stable(path):
    identifiers = set(string.Template(path.read_text(encoding="utf-8")).get_identifiers())
    assert identifiers <= _STATIC_PLACEHOLDERS, f"{path}: per-call placeholders {identifiers - _STATIC_PLACEHOLDERS}"
    values = dict.fromkeys(identifiers, "a, b, c")
    first = load_prompt(path.parent.name, path.name, values)
    second = load_prompt(path.parent.name, path.name, dict(values))
    assert first.encode("utf-8") == second.encode("utf-8")
    assert not any(ch in first for ch in ("\r", "\x00")), "no line-ending or control drift in a cached prefix"
