"""RUN-FAIL-1: the google adapter sends the tool loop's OpenAI-style function specs as Gemini function declarations.

Live, every unit holding a tool (web-research: web_search, fetch_url) failed in under a second on Vertex: the adapter
put `{"type": "function", "function": {...}}` into the Gen AI SDK's `GenerateContentConfig`, which refuses that shape
before sending (pydantic `extra_forbidden`). These tests build the REAL SDK objects (`google.genai.types`, not
`_fake_genai_sdk`), so the SDK's own validation decides; the network client is a fake (no call leaves).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from google.genai import types as real_genai_types
from tilo_contracts import ProvidersProfile
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.interfaces import GenerateRequest

SEARCH = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the public web.",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 300}},
        },
    },
}
FETCH = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": "Fetch one public page.",
        "parameters": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}},
    },
}


class _Models:
    def __init__(self) -> None:
        self.configs: list[Any] = []

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.configs.append(config)
        call = SimpleNamespace(name="web_search", args={"query": "Gokarna"})
        return SimpleNamespace(
            prompt_feedback=None,
            candidates=[SimpleNamespace(finish_reason="STOP")],
            usage_metadata=None,
            function_calls=[call],
            text=None,
        )


def _provider(models: _Models) -> GoogleModelProvider:
    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "gemini-3.1-flash-lite", "context": 1_000_000, "caps": ["json", "tools"]}
    )
    return GoogleModelProvider(profile, "lite-31", "demo-tilo", "global", client=SimpleNamespace(models=models))


def test_RUN_FAIL_1_openai_style_tools_reach_the_real_sdk_as_function_declarations():
    models = _Models()

    response = _provider(models).generate(GenerateRequest(prompt="Plan the stops.", tools=[SEARCH, FETCH]))

    assert response.tool_calls == [{"name": "web_search", "args": {"query": "Gokarna"}}]
    (config,) = models.configs
    assert isinstance(config, real_genai_types.GenerateContentConfig)
    (tool,) = config.tools
    declarations = {d.name: d for d in tool.function_declarations}
    assert set(declarations) == {"web_search", "fetch_url"}
    search = declarations["web_search"]
    assert search.description == "Search the public web."
    assert search.parameters_json_schema["required"] == ["query"]
    assert "additionalProperties" not in search.parameters_json_schema, "Gemini's subset only (to_gemini_schema)"


def test_RUN_FAIL_1_the_sdk_accepts_the_config_the_adapter_builds_for_tools():
    provider = _provider(_Models())

    kwargs = provider._config_kwargs(GenerateRequest(prompt="x", tools=[SEARCH]))

    real_genai_types.GenerateContentConfig(**kwargs)  # raises if the SDK refuses the shape
    assert kwargs["tools"][0]["function_declarations"][0]["name"] == "web_search"


def test_RUN_FAIL_1_a_gemini_shaped_tool_passes_unchanged():
    native = {"function_declarations": [{"name": "lookup", "description": "Look up."}]}
    provider = _provider(_Models())

    assert provider._config_kwargs(GenerateRequest(prompt="x", tools=[native]))["tools"] == [native]
