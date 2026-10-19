"""FR-INT-03 / FR-INT-06 / FR-INT-09, EFF-02, live run 2 of 8 Oct 2026 (13.5 credits for a simple ask): the Director's
planning calls sent no `thinking_level`, so the model's own default (dynamic, high on Gemini 3.x) ran and its thinking
tokens were billed as output. Each call now states the level it needs: brief extraction `low`, the approaches and the
plan compile `medium`. A scripted provider records the request the Router sent it: no model, no network."""

from __future__ import annotations

import copy
import json

from _plan_validator_lib import (
    approaches_2,
    build_fake_connectors,
    build_fake_policies,
    build_fake_skills,
    build_risk_table,
    load_plan_fixture,
)
from _planning_contracts_lib import (
    ScriptedCall,
    ScriptedModelProvider,
    build_test_router,
    load_approaches_fixture,
    load_brief_fixture,
    sample_event_base,
)
from tilo_planning.approaches import propose_approaches
from tilo_planning.brief import complete_brief, extract_brief
from tilo_planning.compiler import PlanInputs, compile_plan


def _brief() -> dict:
    return complete_brief(load_brief_fixture("valid_market_scan"))


def test_FR_INT_03_brief_extraction_asks_for_low_thinking(tmp_path) -> None:
    reply = json.dumps(load_brief_fixture("valid_market_scan"))
    provider = ScriptedModelProvider("large", [ScriptedCall(text=reply)])

    extract_brief("Prepare the market scan.", router=build_test_router(tmp_path, provider))

    assert [call.thinking_level for call in provider.calls] == ["low"]


def test_FR_INT_06_the_approaches_call_asks_for_medium_thinking(tmp_path) -> None:
    reply = json.dumps(load_approaches_fixture("distinct_three"))
    provider = ScriptedModelProvider("large", [ScriptedCall(text=reply)])

    propose_approaches(_brief(), router=build_test_router(tmp_path, provider), base=sample_event_base(), seq=2)

    assert [call.thinking_level for call in provider.calls] == ["medium"]


def test_FR_INT_09_the_plan_compile_call_asks_for_medium_thinking(tmp_path) -> None:
    units = copy.deepcopy(load_plan_fixture("valid", "two_approaches_email_send_gated")["units"])
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps({"units": units}))])
    inputs = PlanInputs(
        approaches=approaches_2(),
        owner="u_owner",
        skills={s: f"The {s} skill." for s in sorted(build_fake_skills())},
        connectors=build_fake_connectors(),
        risk_table=build_risk_table(),
        policies=build_fake_policies(),
    )
    approach = next(a for a in inputs.approaches if a["id"] == "quick")

    compile_plan(_brief(), approach, 42.5, inputs, router=build_test_router(tmp_path, provider))

    assert {call.thinking_level for call in provider.calls} == {"medium"}
