"""GOOGLE-MAX (PL-01, 16 Oct 2026): two more Google switches in the provider layer, no contract change, no network.

1. Gemini code execution. A request that carries `{"code_execution": {}}` runs Python in Google's sandbox; the adapter
   declares it only for a profile with the `code_execution` capability, and surfaces each run (code, outcome, output) as
   `GenerateResponse.code_runs`, so the caller can show what was computed instead of trusting prose (HR-1).
2. Grounding citations. `GoogleSearchProvider` keeps Gemini's `grounding_supports` (which claim rests on which source)
   as `SearchResult.citations`, indexes into `sources`, next to the sources it already returned.

Real SDK types (`google.genai.types`) shape the replies; the client is a fake, so nothing leaves the host."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import types as sdk
from tilo_contracts import ProvidersProfile
from tilo_providers.errors import RequestError
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.google_search_adapter import GoogleSearchProvider
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.search import SearchResult

CODE = {"code_execution": {}}


class _Models:
    def __init__(self, response: Any) -> None:
        self.response, self.configs = response, []

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.configs.append(config)
        return self.response


def _code_reply(*, parts: list[sdk.Part]) -> sdk.GenerateContentResponse:
    return sdk.GenerateContentResponse(
        candidates=[sdk.Candidate(content=sdk.Content(role="model", parts=parts), finish_reason="STOP")],
        usage_metadata=sdk.GenerateContentResponseUsageMetadata(
            prompt_token_count=20, candidates_token_count=30, total_token_count=50
        ),
    )


def _model(models: _Models, caps: list[str]) -> GoogleModelProvider:
    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "example-model", "context": 1_000_000, "caps": caps}
    )
    return GoogleModelProvider(profile, "flash-x", "demo-tilo", "global", client=SimpleNamespace(models=models))


def test_PL_01_google_max_code_execution_tool_reaches_the_real_sdk_and_runs_are_surfaced():
    parts = [
        sdk.Part(text="I will compute it."),
        sdk.Part(executable_code=sdk.ExecutableCode(language="PYTHON", code="print(sum(range(5)))")),
        sdk.Part(code_execution_result=sdk.CodeExecutionResult(outcome="OUTCOME_OK", output="10\n")),
        sdk.Part(text="The sum is 10."),
    ]
    models = _Models(_code_reply(parts=parts))

    reply = _model(models, ["json", "code_execution"]).generate(GenerateRequest(prompt="Sum 0..4", tools=[CODE]))

    assert models.configs[0].tools[0].code_execution is not None  # the SDK accepted the tool
    assert reply.code_runs == [
        {"language": "PYTHON", "code": "print(sum(range(5)))", "outcome": "OUTCOME_OK", "output": "10\n"}
    ]
    assert "The sum is 10." in (reply.text or "")
    assert reply.usage == {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50, "cached_tokens": 0}


def test_PL_01_google_max_a_failed_run_is_reported_with_its_outcome_and_a_reply_without_code_has_none():
    failed = [
        sdk.Part(executable_code=sdk.ExecutableCode(language="PYTHON", code="1/0")),
        sdk.Part(code_execution_result=sdk.CodeExecutionResult(outcome="OUTCOME_FAILED", output="ZeroDivisionError")),
    ]
    provider = _model(_Models(_code_reply(parts=failed)), ["code_execution"])
    (run,) = provider.generate(GenerateRequest(prompt="x", tools=[CODE])).code_runs or []
    assert run["outcome"] == "OUTCOME_FAILED" and run["output"] == "ZeroDivisionError"

    plain = _model(_Models(_code_reply(parts=[sdk.Part(text="hello")])), ["code_execution"])
    assert plain.generate(GenerateRequest(prompt="x", tools=[CODE])).code_runs is None


def test_PL_01_google_max_runs_and_output_are_capped():
    parts: list[sdk.Part] = []
    for i in range(12):
        parts += [
            sdk.Part(executable_code=sdk.ExecutableCode(language="PYTHON", code=f"print({i})")),
            sdk.Part(code_execution_result=sdk.CodeExecutionResult(outcome="OUTCOME_OK", output="x" * 9000)),
        ]
    runs = (
        _model(_Models(_code_reply(parts=parts)), ["code_execution"])
        .generate(GenerateRequest(prompt="x", tools=[CODE]))
        .code_runs
    )
    assert runs is not None and len(runs) == 8 and all(len(r["output"]) <= 4000 for r in runs)


@pytest.mark.parametrize("tools", [[{"code_execution": {"x": 1}}], [{"code_execution": None}]])
def test_PL_01_google_max_code_execution_takes_no_options(tools):
    models = _Models(_code_reply(parts=[sdk.Part(text="x")]))
    with pytest.raises(RequestError):
        _model(models, ["code_execution"]).generate(GenerateRequest(prompt="x", tools=tools))
    assert models.configs == []


def test_PL_01_google_max_a_profile_without_the_capability_is_refused_before_anything_is_sent():
    models = _Models(_code_reply(parts=[sdk.Part(text="x")]))
    with pytest.raises(RequestError, match="code_execution"):
        _model(models, ["json", "tools"]).generate(GenerateRequest(prompt="x", tools=[CODE]))
    assert models.configs == []


# --- grounding citations ------------------------------------------------------------------------------------------

REDIRECT = "https://vertexaisearch.example/grounding-api-redirect/"


def _grounded(supports: list[sdk.GroundingSupport], chunk_uris: list[str]) -> sdk.GenerateContentResponse:
    metadata = sdk.GroundingMetadata(
        web_search_queries=["q one"],
        grounding_chunks=[
            sdk.GroundingChunk(web=sdk.GroundingChunkWeb(uri=u, title=f"T{i}", domain=f"d{i}.example"))
            for i, u in enumerate(chunk_uris)
        ],
        grounding_supports=supports,
    )
    candidate = sdk.Candidate(
        content=sdk.Content(role="model", parts=[sdk.Part(text="Paris is the capital. It is large.")]),
        finish_reason="STOP",
        grounding_metadata=metadata,
    )
    return sdk.GenerateContentResponse(
        candidates=[candidate],
        usage_metadata=sdk.GenerateContentResponseUsageMetadata(
            prompt_token_count=10, candidates_token_count=5, total_token_count=15
        ),
    )


def _search(response: Any) -> SearchResult:
    profile = ProvidersProfile.model_validate(
        {"provider": "google", "model": "example-search", "context": 1_000_000, "caps": ["json", "grounding"]}
    )
    provider = GoogleSearchProvider(
        profile, "search-google", "demo-tilo", "global", client=SimpleNamespace(models=_Models(response))
    )
    return provider.search("capital of france")


def _support(text: str, start: int, end: int, chunks: list[int]) -> sdk.GroundingSupport:
    return sdk.GroundingSupport(
        segment=sdk.Segment(text=text, start_index=start, end_index=end), grounding_chunk_indices=chunks
    )


def test_PL_01_google_max_citations_map_each_claim_to_the_source_that_supports_it():
    result = _search(
        _grounded(
            [_support("Paris is the capital.", 0, 21, [1, 0]), _support("It is large.", 22, 34, [1])],
            [REDIRECT + "a", REDIRECT + "b"],
        )
    )
    assert [s.redirect_url for s in result.sources] == [REDIRECT + "a", REDIRECT + "b"]
    assert [(c.start, c.end, c.text, c.sources) for c in result.citations] == [
        (0, 21, "Paris is the capital.", [0, 1]),
        (22, 34, "It is large.", [1]),
    ]


def test_PL_01_google_max_citations_follow_sources_when_a_chunk_is_dropped_or_repeated():
    # chunk 0 has an http (refused) address, chunk 2 repeats chunk 1's address: indexes must point at `sources`.
    uris = ["http://insecure.example/x", REDIRECT + "b", REDIRECT + "b"]
    result = _search(_grounded([_support("Paris is the capital.", 0, 21, [0, 2, 9])], uris))
    assert [s.redirect_url for s in result.sources] == [REDIRECT + "b"]
    assert [c.sources for c in result.citations] == [[0]]


def test_PL_01_google_max_a_support_with_no_usable_source_is_left_out_and_citations_are_capped():
    supports = [_support("none", 0, 4, [7])] + [_support(f"claim {i}", i, i + 1, [0]) for i in range(30)]
    result = _search(_grounded(supports, [REDIRECT + "a"]))
    assert len(result.citations) == 12 and all(c.sources == [0] for c in result.citations)
    assert all(len(c.text) <= 160 for c in result.citations)


def test_PL_01_google_max_a_reply_without_supports_has_no_citations_and_old_recordings_still_load():
    assert _search(_grounded([], [REDIRECT + "a"])).citations == []
    old = {"query": "q", "answer": "a", "sources": [], "queries": [], "profile_id": "p"}  # pre-GOOGLE-MAX recording
    assert SearchResult.model_validate(old).citations == []
