"""PL-02 live-run fix: a Vertex request never carries thinking level MINIMAL.

packages/providers/CLAUDE.md records that Vertex answers HTTP 400 to `thinking_level` "minimal" (live, 5 Oct 2026), yet
`live_e2e` (units, narrator) and the generator ask for it. The Google adapter talks to Vertex only (`vertexai=True`), so
it maps "minimal" to "low" when it builds the config; the OpenAI-compatible adapter ignores
`thinking_level` and is untouched. These tests build the
request through the real `google.genai` SDK and cut the network at the transport (`request` / `request_streamed`), like
test_PL_02_response_json_schema_real_sdk.py: no credentials, no network, no paid call.
"""

from __future__ import annotations

from typing import Any

import pytest
from google import genai
from google.auth.credentials import AnonymousCredentials
from google.genai import _api_client
from tilo_contracts import ProvidersProfile
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.interfaces import GenerateRequest


class _NotSent(Exception):
    pass


def _provider(sent: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, caps: list[str]) -> GoogleModelProvider:
    def stub(self: object, http_method: str, path: str, request_dict: dict[str, Any], *_a: Any, **_k: Any) -> Any:
        sent.append(request_dict)
        raise _NotSent

    monkeypatch.setattr(_api_client.BaseApiClient, "request", stub)
    monkeypatch.setattr(_api_client.BaseApiClient, "request_streamed", stub)
    client = genai.Client(
        vertexai=True, project="tilo-test-project", location="global", credentials=AnonymousCredentials()
    )
    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "placeholder-model", "context": 1_000_000, "caps": caps}
    )
    return GoogleModelProvider(
        profile=profile, profile_id="flash-38", project="tilo-test-project", location="global", client=client
    )


def _level(sent: list[dict[str, Any]]) -> Any:
    (body,) = sent
    level = body["generationConfig"]["thinkingConfig"]["thinking_level"]  # the SDK's enum, snake_case until it is sent
    return getattr(level, "value", level)


@pytest.mark.parametrize("mode", ["generate", "stream"])
def test_PL_02_a_vertex_request_never_carries_thinking_level_minimal(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []
    provider = _provider(sent, monkeypatch, ["json", "thinking"])
    request = GenerateRequest(prompt="hello", max_output_tokens=64, thinking_level="minimal")
    with pytest.raises(_NotSent):
        provider.generate(request) if mode == "generate" else list(provider.stream(request))
    assert str(_level(sent)).upper() == "LOW", "minimal is mapped to low for Vertex"
    assert "MINIMAL" not in str(sent[0]).upper()
    assert request.thinking_level == "minimal", "the caller's request is not changed"


@pytest.mark.parametrize("level", ["low", "medium", "high"])
def test_PL_02_the_other_thinking_levels_pass_through_to_vertex_unchanged(
    level: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []
    provider = _provider(sent, monkeypatch, ["json", "thinking"])
    with pytest.raises(_NotSent):
        provider.generate(GenerateRequest(prompt="hello", max_output_tokens=64, thinking_level=level))
    assert str(_level(sent)).upper() == level.upper()


def test_PL_02_a_profile_without_the_thinking_capability_sends_no_thinking_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[dict[str, Any]] = []
    provider = _provider(sent, monkeypatch, ["json"])
    with pytest.raises(_NotSent):
        provider.generate(GenerateRequest(prompt="hello", max_output_tokens=64, thinking_level="minimal"))
    assert "thinkingConfig" not in sent[0].get("generationConfig", {})
