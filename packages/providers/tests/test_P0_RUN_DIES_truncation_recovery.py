"""P0-RUN-DIES: a paid MAX_TOKENS answer gets one useful same-profile retry before fallback."""

from __future__ import annotations

from pathlib import Path

from conftest import ScriptedCall, ScriptedModelProvider
from tilo_providers.config import load_providers_config
from tilo_providers.errors import OutputTruncatedError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router


def _cut() -> OutputTruncatedError:
    return OutputTruncatedError("reply hit its cap", input_tokens=10, output_tokens=0, thinking_tokens=1024)


def test_P0_RUN_DIES_router_retries_the_same_profile_once_with_more_room_and_less_thinking(
    providers_config,
) -> None:
    primary = ScriptedModelProvider(
        "large",
        [ScriptedCall(outcome="error", error=_cut()), ScriptedCall(text="complete answer")],
    )
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="fallback")])

    result = Router(
        providers_config,
        provider_for_profile={"large": primary, "medium": fallback}.__getitem__,
    ).generate("director", GenerateRequest(prompt="Draft the answer."))

    assert result.response is not None and result.response.text == "complete answer"
    assert len(primary.calls) == 2 and fallback.calls == []
    assert [call.max_output_tokens for call in primary.calls] == [1024, 2048]
    assert [call.thinking_level for call in primary.calls] == ["high", "medium"]
    assert [attempt.error_type for attempt in result.attempts] == ["OutputTruncatedError", None]
    assert "truncated" in (result.attempts[1].reason or "")


def test_P0_RUN_DIES_router_falls_back_after_the_one_larger_same_profile_retry(providers_config) -> None:
    primary = ScriptedModelProvider(
        "large",
        [ScriptedCall(outcome="error", error=_cut()), ScriptedCall(outcome="error", error=_cut())],
    )
    fallback = ScriptedModelProvider("medium", [ScriptedCall(text="fallback completed")])

    result = Router(
        providers_config,
        provider_for_profile={"large": primary, "medium": fallback}.__getitem__,
    ).generate("director", GenerateRequest(prompt="Draft the answer."))

    assert result.response is not None and result.response.text == "fallback completed"
    assert [call.max_output_tokens for call in primary.calls] == [1024, 2048]
    assert fallback.calls[0].max_output_tokens == 2048
    assert [attempt.profile_id for attempt in result.attempts] == ["large", "large", "medium"]


def test_P0_RUN_DIES_live_google_writing_roles_have_32768_output_caps(repo_root: Path) -> None:
    for name in ("models.yaml", "models.gemini.yaml"):
        config = load_providers_config(repo_root / "config" / name, repo_root / "config" / "prices.yaml")
        caps = {role: config.roles[role].max_output_tokens for role in ("generator", "specialist", "lead", "writer")}
        assert caps == {
            "generator": 32768,
            "specialist": 32768,
            "lead": 32768,
            "writer": 32768,
        }, name
