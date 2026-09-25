"""EFF-03 (PRD 6.6 Cost efficiency, "Small contexts"): "Per-role token caps;
tool outputs compacted before they reach a model." Acceptance test: "A call
over its cap is compacted or refused, never silently sent."

Ticket P0-06 item 3: count tokens with the provider's `count_tokens`; if
over `max_input_tokens`, apply a deterministic compactor (drop oldest tool
outputs first, then truncate the longest tool output with a marker) or
refuse with a clear error; never send over the cap; always pass
`max_output_tokens`.

Ambiguity (docs/open-questions.md BQ-53): `GenerateRequest` (frozen in
ticket P0-05, `extra="forbid"`) has no field for prior tool call outputs, so
these are passed to `Router.generate(..., tool_outputs=[...])` (oldest
first) and folded into the final prompt the router sends the provider,
after compaction. `ScriptedModelProvider.count_tokens` counts words (like
`FakeModelProvider`), so these tests use word counts as the token cap.

Ambiguity (docs/open-questions.md BQ-54): when both the caller and the
role's config set `max_output_tokens`, the caller's explicit value is
respected; the role's value only fills in when the caller left it unset.
"""

from __future__ import annotations

import pytest
from conftest import ScriptedCall, ScriptedModelProvider, token_cap_models_config, write_providers_config
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
