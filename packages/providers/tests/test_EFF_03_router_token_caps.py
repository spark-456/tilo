"""EFF-03 (PRD 6.6 Cost efficiency, "Small contexts"): "Per-role token caps;
tool outputs compacted before they reach a model." Acceptance test: "A call
over its cap is compacted or refused, never silently sent."

Ticket P0-06 item 3: count tokens with the provider's `count_tokens`; if
over `max_input_tokens`, apply a deterministic compactor (drop oldest tool
outputs first, then truncate the longest tool output with a marker) or
refuse with a clear error; never send over the cap; always pass
`max_output_tokens`.

Ambiguity (docs/open-questions.md BQ-62): `GenerateRequest` (frozen in
ticket P0-05, `extra="forbid"`) has no field for prior tool call outputs, so
these are passed to `Router.generate(..., tool_outputs=[...])` (oldest
first) and folded into the final prompt the router sends the provider,
after compaction. `ScriptedModelProvider.count_tokens` counts words (like
`FakeModelProvider`), so these tests use word counts as the token cap.

Ambiguity (docs/open-questions.md BQ-63): when both the caller and the
role's config set `max_output_tokens`, the caller's explicit value is
respected; the role's value only fills in when the caller left it unset.
"""

from __future__ import annotations

import json

import pytest
from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    token_cap_models_config,
    token_cap_tiered_models_config,
    write_providers_config,
)
from tilo_providers.errors import QuotaError
from tilo_providers.interfaces import GenerateRequest


def _config(tmp_path):
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    models_path, prices_path = write_providers_config(
        tmp_path,
        token_cap_models_config(),
        {
            "status": "set",
            "effective_date": "2026-10-01",
            "source": "Fake provider price page, retrieved 2026-10-01",
            "currency": "USD",
            "credit_usd": 0.005,
            "profiles": {"capped": {"input": 0.1, "output": 0.2}},
        },
    )
    return load_providers_config(models_path, prices_path)


def _router(config, provider: ScriptedModelProvider):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile={"capped": provider}.__getitem__)


def _tiered_config(tmp_path):
    """Two distinct profiles ("primary-cap", "fallback-cap"), role "tiered", `max_input_tokens=10`."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    models_path, prices_path = write_providers_config(
        tmp_path,
        token_cap_tiered_models_config(),
        {
            "status": "set",
            "effective_date": "2026-10-01",
            "source": "Fake provider price page, retrieved 2026-10-01",
            "currency": "USD",
            "credit_usd": 0.005,
            "profiles": {"primary-cap": {"input": 0.1, "output": 0.2}, "fallback-cap": {"input": 0.1, "output": 0.2}},
        },
    )
    return load_providers_config(models_path, prices_path)


def _tiered_router(config, providers: dict[str, ScriptedModelProvider]):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


class _MultiplierTokenizer(ScriptedModelProvider):
    """A `ScriptedModelProvider` whose `count_tokens` counts `multiplier` tokens per word -- standing in
    for a candidate whose real tokenizer counts the very same text differently from the candidate the
    router already compacted the prompt for (EFF-03 review follow-up: "a profile with a different
    tokenizer can be sent a prompt over the role cap")."""

    def __init__(self, profile_id: str, script: list[ScriptedCall], *, multiplier: int) -> None:
        super().__init__(profile_id, script)
        self._multiplier = multiplier

    def count_tokens(self, text: str) -> int:
        return len(text.split()) * self._multiplier


_TIERED_TOOL_OUTPUTS = ["ALPHA ALPHA ALPHA ALPHA", "BRAVO BRAVO", "CHARLIE CHARLIE CHARLIE"]  # see test 1 above


def test_EFF_03_input_over_cap_drops_oldest_tool_outputs_first(tmp_path):
    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="summary")])
    router = _router(config, provider)

    # role "summariser" caps max_input_tokens at 10 words. prompt=3 words;
    # oldest tool output=4 words; newest two=2+3=5 words. Total=12 (over);
    # dropping only the oldest leaves 3+2+3=8 (under) -- nothing else needs
    # to be touched.
    result = router.generate(
        "summariser",
        GenerateRequest(prompt="summarize the following"),
        tool_outputs=["ALPHA ALPHA ALPHA ALPHA", "BRAVO BRAVO", "CHARLIE CHARLIE CHARLIE"],
    )

    assert result.outcome == "ok"
    sent = provider.calls[0]
    assert "ALPHA" not in sent.prompt, "the oldest tool output must be dropped first"
    assert "BRAVO" in sent.prompt
    assert "CHARLIE" in sent.prompt
    assert len(sent.prompt.split()) <= 10, "the compacted request must never be sent over the cap"


def test_EFF_03_input_still_over_cap_truncates_longest_remaining_tool_output_with_marker(tmp_path):
    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="summary")])
    router = _router(config, provider)

    # prompt=3 words; oldest tool output ALPHA=2 words (droppable); the only
    # remaining one, BRAVO, is 20 words on its own -- even after dropping
    # ALPHA the total (3+20=23) is still over the 10-word cap, so BRAVO
    # itself must be truncated with a marker.
    result = router.generate(
        "summariser",
        GenerateRequest(prompt="summarize the following"),
        tool_outputs=["ALPHA ALPHA", " ".join(["BRAVO"] * 20)],
    )

    assert result.outcome == "ok"
    sent = provider.calls[0]
    assert "ALPHA" not in sent.prompt, "a droppable tool output is dropped before any truncation happens"
    assert "BRAVO" in sent.prompt, "the remaining tool output is truncated, not dropped entirely"
    assert sent.prompt.count("BRAVO") < 20, "the remaining tool output must actually be shortened"
    assert len(sent.prompt.split()) <= 10
    assert "truncat" in sent.prompt.lower(), "a truncation marker must show the output was cut"


def test_EFF_03_input_over_cap_with_nothing_left_to_compact_is_refused(tmp_path):
    from tilo_providers.router import TokenCapExceededError  # noqa: PLC0415

    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="must never be reached")])
    router = _router(config, provider)

    long_prompt = " ".join(["word"] * 15)  # 15 words > the 10-word cap, no tool_outputs to compact

    with pytest.raises(TokenCapExceededError):
        router.generate("summariser", GenerateRequest(prompt=long_prompt))

    assert provider.calls == [], "an over-cap request that cannot be compacted must never be sent"


def test_EFF_03_role_max_output_tokens_fills_an_unset_request(tmp_path):
    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="ok")])
    router = _router(config, provider)

    router.generate("summariser", GenerateRequest(prompt="short prompt"))

    assert provider.calls[0].max_output_tokens == 50, "role.max_output_tokens must always be passed down"


def test_EFF_03_explicit_max_output_tokens_is_respected(tmp_path):
    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="ok")])
    router = _router(config, provider)

    router.generate("summariser", GenerateRequest(prompt="short prompt", max_output_tokens=5))

    assert provider.calls[0].max_output_tokens == 5, "an explicit request value must not be silently overridden"


# --- Review follow-up (ticket P0-06): `_start` only compacts the prompt against the *first* candidate's
# `count_tokens`. A fallback, a cascade escalation, or a stream fallback moves the router to a different
# candidate whose own tokenizer may count the very same (already-compacted) text differently -- each one
# must be checked and recompacted (or refused) with its own `count_tokens` before it is ever sent.


def test_EFF_03_fallback_is_recompacted_for_its_own_tokenizer_and_sent(tmp_path):
    config = _tiered_config(tmp_path)
    primary = ScriptedModelProvider("primary-cap", [ScriptedCall(outcome="error", error=QuotaError("rate limited"))])
    fallback = _MultiplierTokenizer("fallback-cap", [ScriptedCall(text="ok from fallback")], multiplier=2)
    router = _tiered_router(config, {"primary-cap": primary, "fallback-cap": fallback})

    # primary's own (word-count) tokenizer compacts prompt+outputs to "...BRAVO BRAVO CHARLIE CHARLIE
    # CHARLIE" (8 words, <=10) before primary is even called; primary then errors and the router falls
    # back to "fallback-cap", whose tokenizer counts *2 -- 8 words is 16, over the cap, so it must be
    # recompacted from scratch for that tokenizer, not sent as-is.
    result = router.generate(
        "tiered", GenerateRequest(prompt="summarize the following"), tool_outputs=list(_TIERED_TOOL_OUTPUTS)
    )

    assert result.outcome == "ok"
    assert [a.profile_id for a in result.attempts] == ["primary-cap", "fallback-cap"]
    sent = fallback.calls[0]
    assert fallback.count_tokens(sent.prompt) <= 10, (
        "the fallback must never be sent over its own token count of the cap"
    )
    assert "ALPHA" not in sent.prompt
    assert "BRAVO" not in sent.prompt, "the fallback's stricter tokenizer forces a fresh compaction pass"
    assert "CHARLIE" in sent.prompt
    assert "truncat" in sent.prompt.lower()


def test_EFF_03_fallback_still_over_cap_after_recompaction_is_refused_and_recorded(tmp_path):
    from tilo_providers.router import RouterExhaustedError  # noqa: PLC0415

    config = _tiered_config(tmp_path)
    primary = ScriptedModelProvider("primary-cap", [ScriptedCall(outcome="error", error=QuotaError("rate limited"))])
    fallback = _MultiplierTokenizer("fallback-cap", [ScriptedCall(text="must never be reached")], multiplier=3)
    router = _tiered_router(config, {"primary-cap": primary, "fallback-cap": fallback})

    with pytest.raises(RouterExhaustedError) as excinfo:
        router.generate(
            "tiered", GenerateRequest(prompt="summarize the following"), tool_outputs=list(_TIERED_TOOL_OUTPUTS)
        )

    assert fallback.calls == [], "a fallback that cannot fit even after recompaction must never be sent"
    attempts = excinfo.value.attempts
    assert [a.profile_id for a in attempts] == ["primary-cap", "fallback-cap"]
    assert attempts[-1].outcome == "error"
    assert attempts[-1].error_type == "TokenCapExceededError", "the refusal must be recorded in the attempts"


def test_EFF_03_cascade_escalation_is_recompacted_for_its_own_tokenizer(tmp_path):
    """Same gap on the EFF-02 escalation path (schema failure / verifier rejection / low confidence),
    not only on a provider-error fallback: the escalated candidate still gets its own tokenizer's cap
    check, not the cheaper candidate's already-compacted prompt."""
    config = _tiered_config(tmp_path)
    primary = ScriptedModelProvider("primary-cap", [ScriptedCall(text="mediocre answer")])
    fallback = _MultiplierTokenizer("fallback-cap", [ScriptedCall(text="confident answer")], multiplier=2)
    router = _tiered_router(config, {"primary-cap": primary, "fallback-cap": fallback})

    result = router.generate(
        "tiered",
        GenerateRequest(prompt="summarize the following"),
        tool_outputs=list(_TIERED_TOOL_OUTPUTS),
        verify=lambda response: response.text == "confident answer",
    )

    assert result.outcome == "ok"
    assert [a.profile_id for a in result.attempts] == ["primary-cap", "fallback-cap"]
    sent = fallback.calls[0]
    assert fallback.count_tokens(sent.prompt) <= 10
    assert "BRAVO" not in sent.prompt, "escalation must recompact for the next tier's own tokenizer too"


def test_EFF_03_stream_fallback_is_recompacted_for_its_own_tokenizer(tmp_path):
    config = _tiered_config(tmp_path)
    primary = ScriptedModelProvider("primary-cap", [ScriptedCall(outcome="error", error=QuotaError("rate limited"))])
    fallback = _MultiplierTokenizer("fallback-cap", [ScriptedCall(text="ok from fallback")], multiplier=2)
    router = _tiered_router(config, {"primary-cap": primary, "fallback-cap": fallback})

    stream = router.stream(
        "tiered", GenerateRequest(prompt="summarize the following"), tool_outputs=list(_TIERED_TOOL_OUTPUTS)
    )

    assert [chunk.text for chunk in stream] == ["ok from fallback"]
    sent = fallback.calls[0]
    assert fallback.count_tokens(sent.prompt) <= 10
    assert "BRAVO" not in sent.prompt


# --- Review follow-up (ticket P0-06): the cap and the price cover everything sent -- system, prompt, tool
# outputs and the serialised tool definitions and response schema -- not only the prompt and tool outputs.

_SYSTEM_6 = "you are a terse careful summariser"  # 6 words
_TOOLS_12 = [{"name": "lookup", "description": " ".join(["word"] * 12)}]  # well over 10 words once serialised


def _sent_words(request: GenerateRequest) -> int:
    """Every word of what the provider was sent: system, prompt, tool definitions, response schema."""
    texts = [request.system or "", request.prompt]
    texts += [json.dumps(part) for part in (request.tools, request.response_schema) if part is not None]
    return sum(len(text.split()) for text in texts)


def test_EFF_03_system_counts_toward_the_cap_and_forces_compaction(tmp_path):
    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="summary")])
    router = _router(config, provider)

    # prompt+outputs alone are 3+2+3=8 words (under 10); with the 6-word system they are 14 (over).
    router.generate(
        "summariser",
        GenerateRequest(prompt="summarize the following", system=_SYSTEM_6),
        tool_outputs=["BRAVO BRAVO", "CHARLIE CHARLIE CHARLIE"],
    )

    sent = provider.calls[0]
    assert sent.system == _SYSTEM_6, "the system prompt is sent as given, never compacted"
    assert _sent_words(sent) <= 10, "system + prompt + tool outputs must fit the cap together"
    assert "BRAVO" not in sent.prompt


def test_EFF_03_tools_count_toward_the_cap_and_force_compaction(tmp_path):
    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="summary")])
    router = _router(config, provider)
    tools = [{"name": "lookup", "description": "find it"}]  # a few words once serialised

    router.generate(
        "summariser",
        GenerateRequest(prompt="summarize the following", tools=tools),
        tool_outputs=["BRAVO BRAVO", "CHARLIE CHARLIE CHARLIE"],
    )

    sent = provider.calls[0]
    assert sent.tools == tools
    assert _sent_words(sent) <= 10, "tool definitions + prompt + tool outputs must fit the cap together"
    assert "BRAVO" not in sent.prompt


def test_EFF_03_large_system_over_one_candidates_cap_is_refused_recorded_and_falls_back(tmp_path):
    config = _tiered_config(tmp_path)
    primary = _MultiplierTokenizer("primary-cap", [ScriptedCall(text="must never be reached")], multiplier=2)
    fallback = ScriptedModelProvider("fallback-cap", [ScriptedCall(text="ok from fallback")])
    router = _tiered_router(config, {"primary-cap": primary, "fallback-cap": fallback})

    # primary counts the 6-word system alone as 12 tokens (over 10): nothing to compact, so it is refused.
    result = router.generate("tiered", GenerateRequest(prompt="summarize the following", system=_SYSTEM_6))

    assert primary.calls == [], "a candidate whose fixed parts alone are over the cap is never sent"
    assert [a.profile_id for a in result.attempts] == ["primary-cap", "fallback-cap"]
    assert result.attempts[0].error_type == "TokenCapExceededError"
    assert result.response is not None and result.response.text == "ok from fallback"
    assert _sent_words(fallback.calls[0]) <= 10


def test_EFF_03_large_system_over_every_candidates_cap_is_refused(tmp_path):
    from tilo_providers.router import TokenCapExceededError  # noqa: PLC0415

    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="must never be reached")])
    router = _router(config, provider)

    with pytest.raises(TokenCapExceededError) as excinfo:
        router.generate("summariser", GenerateRequest(prompt="hi", system=" ".join(["rule"] * 12)))

    assert provider.calls == []
    assert {a.error_type for a in excinfo.value.attempts} == {"TokenCapExceededError"}


def test_EFF_03_large_tools_over_the_cap_are_refused(tmp_path):
    from tilo_providers.router import TokenCapExceededError  # noqa: PLC0415

    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="must never be reached")])
    router = _router(config, provider)

    with pytest.raises(TokenCapExceededError):
        router.generate("summariser", GenerateRequest(prompt="hi", tools=_TOOLS_12), tool_outputs=["ALPHA"])

    assert provider.calls == [], "tool definitions over the cap on their own are never sent"


def test_EFF_03_large_response_schema_over_the_cap_is_refused(tmp_path):
    from tilo_providers.router import TokenCapExceededError  # noqa: PLC0415

    config = _config(tmp_path)
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="must never be reached")])
    router = _router(config, provider)
    schema = {"type": "object", "properties": {f"field_{i}": {"type": "string"} for i in range(6)}}

    with pytest.raises(TokenCapExceededError):
        router.generate("summariser", GenerateRequest(prompt="hi", response_schema=schema))

    assert provider.calls == [], "a response schema is sent too, so it counts toward the cap"


def test_EFF_03_price_covers_system_and_tools_not_only_the_prompt(tmp_path):
    from tilo_providers.router import BudgetExceededError  # noqa: PLC0415

    config = _config(tmp_path)
    quote = config.price("capped")

    def cost(tokens_in: int) -> float:
        return config.credits((tokens_in * quote.input + 50 * quote.output) / 1e6)  # role max_output_tokens=50

    request = GenerateRequest(prompt="summarize", system="be brief", tools=[{"name": "lookup"}])
    provider = ScriptedModelProvider("capped", [ScriptedCall(text="ok")])
    run = _router(config, provider).generate("summariser", request, budget=1.0)
    assert run.budget == pytest.approx(1.0 - cost(_sent_words(provider.calls[0])))
    assert _sent_words(provider.calls[0]) > len(request.prompt.split())

    # a budget that covers the prompt alone but not system + tools is refused before anything is sent
    refused = ScriptedModelProvider("capped", [ScriptedCall(text="must never be reached")])
    budget = (cost(1) + cost(_sent_words(provider.calls[0]))) / 2
    with pytest.raises(BudgetExceededError):
        _router(config, refused).generate("summariser", request, budget=budget)
    assert refused.calls == []


@pytest.mark.parametrize("name", ["models.yaml", "models.gemini.yaml", "models.nim.yaml"])
def test_EFF_03_the_director_role_has_an_input_cap_below_every_profile_context(name):
    """#59 security follow-up: the Director takes the person's task text, so it is capped (BQ-97)."""
    import pathlib  # noqa: PLC0415

    import yaml  # noqa: PLC0415

    config = yaml.safe_load((pathlib.Path(__file__).resolve().parents[3] / "config" / name).read_text("utf-8"))
    role = config["roles"]["director"]
    cap = role["max_input_tokens"]
    # every profile the Director can route to (an embedding profile's small context is not one: RT-05)
    chain = [config["profiles"][role[k]] for k in ("primary", "fallback") if role.get(k)]
    assert chain and isinstance(cap, int) and 0 < cap < min(p["context"] for p in chain if p["context"])
