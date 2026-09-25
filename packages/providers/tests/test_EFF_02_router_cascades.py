"""EFF-02 (PRD 6.6 Cost efficiency, "Cascades"): "Cascade routing per role
with logged escalation reasons." Acceptance test: "Eval report shows the
share of calls completed on the lowest-cost tier, per role." PRD 6.6 table:
"Try the cheap profile first; escalate only on schema failure, Verifier
rejection or low confidence; log every escalation with its reason."

Ticket P0-06 item 2: "escalate only on schema failure (structured output
fails validation, one repair attempt allowed), verifier rejection (caller
signals it) or low confidence (caller-supplied threshold); every escalation
is logged with its reason." Public interface: `Router.generate(role,
request, verify=..., confidence=..., confidence_threshold=...)` on a role
whose config sets a `cascade` list (cheapest profile first).
"""

from __future__ import annotations

from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    cascade_models_config,
    prices_config_for,
    write_providers_config,
)
from tilo_providers.interfaces import GenerateRequest

_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}


def _config(tmp_path):
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    models_path, prices_path = write_providers_config(
        tmp_path,
        cascade_models_config(),
        prices_config_for({"cheap": (0.1, 0.2), "mid": (0.5, 1.0), "rich": (2.0, 4.0)}),
    )
    return load_providers_config(models_path, prices_path)


def _router(config, providers: dict[str, ScriptedModelProvider]):
    from tilo_providers.router import Router  # noqa: PLC0415

    return Router(config, provider_for_profile=providers.__getitem__)


def test_EFF_02_cascade_tries_the_cheapest_profile_first(tmp_path):
    config = _config(tmp_path)
    cheap = ScriptedModelProvider("cheap", [ScriptedCall(text="good enough")])
    mid = ScriptedModelProvider("mid", [ScriptedCall(text="must never be reached")])
    rich = ScriptedModelProvider("rich", [ScriptedCall(text="must never be reached")])
    router = _router(config, {"cheap": cheap, "mid": mid, "rich": rich})

    result = router.generate("analyst", GenerateRequest(prompt="Summarise the leads."))

    assert result.outcome == "ok"
    assert [attempt.profile_id for attempt in result.attempts] == ["cheap"]
    assert mid.calls == []
    assert rich.calls == []


def test_EFF_02_schema_failure_gets_one_repair_attempt_then_escalates_with_reason(tmp_path):
    config = _config(tmp_path)
    cheap = ScriptedModelProvider(
        "cheap",
        [
            ScriptedCall(text="not json at all"),  # first attempt: invalid
            ScriptedCall(text="still not json"),  # one repair attempt: still invalid
        ],
    )
    mid = ScriptedModelProvider("mid", [ScriptedCall(text='{"answer": "ok"}')])
    router = _router(config, {"cheap": cheap, "mid": mid, "rich": ScriptedModelProvider("rich", [])})

    result = router.generate(
        "analyst",
        GenerateRequest(prompt="Extract the answer.", json_mode=True, response_schema=_SCHEMA),
    )

    assert result.outcome == "ok"
    assert result.response is not None
    assert result.response.text == '{"answer": "ok"}'

    # Exactly one repair attempt on the same (cheapest) profile, then
    # escalation to the next cascade tier -- three attempts total.
    assert [attempt.profile_id for attempt in result.attempts] == ["cheap", "cheap", "mid"]
    assert len(cheap.calls) == 2, "exactly one repair attempt is allowed, not more"
    assert result.attempts[0].outcome != "ok"
    assert result.attempts[1].outcome != "ok"
    assert result.attempts[2].outcome == "ok"
    escalation_reason = (result.attempts[2].reason or "").lower()
    assert "schema" in escalation_reason, f"escalation reason must name schema failure, got: {escalation_reason!r}"


def test_EFF_02_verifier_rejection_escalates_with_reason(tmp_path):
    config = _config(tmp_path)
    cheap = ScriptedModelProvider("cheap", [ScriptedCall(text="mediocre answer")])
    mid = ScriptedModelProvider("mid", [ScriptedCall(text="great answer")])
    router = _router(config, {"cheap": cheap, "mid": mid, "rich": ScriptedModelProvider("rich", [])})

    result = router.generate(
        "analyst",
        GenerateRequest(prompt="Write the answer."),
        verify=lambda response: response.text == "great answer",
    )

    assert result.outcome == "ok"
    assert result.response is not None
    assert result.response.text == "great answer"
    assert [attempt.profile_id for attempt in result.attempts] == ["cheap", "mid"]
    # Verifier rejection is not a schema failure: no repair attempt on the
    # same profile, straight to the next cascade tier.
    assert len(cheap.calls) == 1
    escalation_reason = "".join(a.reason or "" for a in result.attempts).lower()
    assert "verif" in escalation_reason, f"escalation reason must name verifier rejection, got: {escalation_reason!r}"


def test_EFF_02_low_confidence_escalates_with_reason(tmp_path):
    config = _config(tmp_path)
    cheap = ScriptedModelProvider("cheap", [ScriptedCall(text="unsure answer")])
    mid = ScriptedModelProvider("mid", [ScriptedCall(text="confident answer")])
    router = _router(config, {"cheap": cheap, "mid": mid, "rich": ScriptedModelProvider("rich", [])})

    confidence_by_text = {"unsure answer": 0.2, "confident answer": 0.9}
    result = router.generate(
        "analyst",
        GenerateRequest(prompt="Write the answer."),
        confidence=lambda response: confidence_by_text[response.text],
        confidence_threshold=0.5,
    )

    assert result.outcome == "ok"
    assert result.response is not None
    assert result.response.text == "confident answer"
    assert [attempt.profile_id for attempt in result.attempts] == ["cheap", "mid"]
    escalation_reason = "".join(a.reason or "" for a in result.attempts).lower()
    assert "confidence" in escalation_reason, f"escalation reason must name low confidence, got: {escalation_reason!r}"


def test_EFF_02_share_of_calls_finished_on_lowest_tier_is_computable_from_call_records(tmp_path):
    """PRD 6.6 EFF-02 acceptance test: "Eval report shows the share of
    calls completed on the lowest-cost tier, per role." Runs the cascade
    role 6 times: 4 finish on "cheap" (the lowest tier), 2 fail verification
    and escalate to "mid" -- the 4/6 share must be computable purely from
    the returned call records (no separate accounting the router keeps for
    itself)."""
    config = _config(tmp_path)
    cheap_texts = ["ok-1", "bad-2", "ok-3", "ok-4", "bad-5", "ok-6"]
    cheap = ScriptedModelProvider("cheap", [ScriptedCall(text=text) for text in cheap_texts])
    mid = ScriptedModelProvider("mid", [ScriptedCall(text="mid-ok-2"), ScriptedCall(text="mid-ok-5")])
    router = _router(config, {"cheap": cheap, "mid": mid, "rich": ScriptedModelProvider("rich", [])})

    results = [
        router.generate(
            "analyst", GenerateRequest(prompt=f"call {i}"), verify=lambda response: "bad" not in response.text
        )
        for i in range(6)
    ]

    assert all(result.outcome == "ok" for result in results)
    assert all(result.attempts[0].profile_id == "cheap" for result in results), "cascade always starts cheapest"

    finished_on_lowest_tier = sum(1 for result in results if len(result.attempts) == 1)
    assert finished_on_lowest_tier == 4
    share = finished_on_lowest_tier / len(results)
    assert share == 4 / 6
