"""FR-INT-03 / FR-INT-06 / FR-INT-09, INTAKE-QUALITY-1 (live run of 9 Oct 2026: a 24-month roadmap starting March 2025
for a Feb 2027 exam, while today was 9 Oct 2026): the Director is told today's date and the time left as plain facts
from an injectable clock, in the brief, approaches and plan prompts (and the repair prompts). Fixed dates, scripted
provider, no network."""

from __future__ import annotations

import copy
import json
from datetime import date

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
from tilo_planning.brief import brief_request, complete_brief, extract_brief
from tilo_planning.compiler import PlanInputs, compile_plan

TODAY = date(2026, 10, 9)
OTHER = date(2026, 11, 20)


def _brief(deadline: str | None = "2027-02-07") -> dict:
    return {**complete_brief(load_brief_fixture("valid_market_scan")), "deadline": deadline}


def _text(request) -> str:
    return f"{request.system or ''}\n{request.prompt}"


def test_FR_INT_03_the_brief_prompt_states_today(tmp_path) -> None:
    request = brief_request("Prepare for the exam.", today=TODAY)

    assert "Today is 2026-10-09" in _text(request)
    assert brief_request("Prepare for the exam.", today=OTHER).prompt != request.prompt


def test_FR_INT_03_extract_brief_passes_the_given_date_to_the_director(tmp_path) -> None:
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps(load_brief_fixture("valid_market_scan")))])

    extract_brief("Prepare the market scan.", router=build_test_router(tmp_path, provider), today=TODAY)

    assert "Today is 2026-10-09" in _text(provider.calls[0])


def test_FR_INT_03_the_brief_prompt_defaults_to_the_real_date() -> None:
    assert f"Today is {date.today().isoformat()}" in _text(brief_request("Prepare for the exam."))


def test_FR_INT_06_the_approaches_prompt_states_today_and_the_days_left(tmp_path) -> None:
    provider = ScriptedModelProvider(
        "large", [ScriptedCall(text=json.dumps(load_approaches_fixture("distinct_three")))]
    )

    propose_approaches(
        _brief(), router=build_test_router(tmp_path, provider), base=sample_event_base(), seq=2, today=TODAY
    )

    prompt = _text(provider.calls[0])
    assert "Today is 2026-10-09" in prompt
    assert "The deadline is 2027-02-07 (121 days from today)" in prompt


def test_FR_INT_06_without_a_deadline_the_approaches_prompt_says_so(tmp_path) -> None:
    provider = ScriptedModelProvider(
        "large", [ScriptedCall(text=json.dumps(load_approaches_fixture("distinct_three")))]
    )

    propose_approaches(
        _brief(None), router=build_test_router(tmp_path, provider), base=sample_event_base(), seq=2, today=TODAY
    )

    assert "The deadline is none stated (no deadline, so plan a sensible span from today)" in _text(provider.calls[0])


def test_FR_INT_06_the_approaches_repair_prompt_keeps_the_date(tmp_path) -> None:
    good = load_approaches_fixture("distinct_three")
    bad = copy.deepcopy(good)
    bad["approaches"][1]["dimensions"] = bad["approaches"][0]["dimensions"]  # PG-08: not distinct
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps(bad)), ScriptedCall(text=json.dumps(good))])

    propose_approaches(
        _brief(), router=build_test_router(tmp_path, provider), base=sample_event_base(), seq=2, today=TODAY
    )

    assert len(provider.calls) == 2
    assert "Today is 2026-10-09" in _text(provider.calls[1])


def _inputs() -> PlanInputs:
    return PlanInputs(
        approaches=approaches_2(),
        owner="u_owner",
        skills={s: f"The {s} skill." for s in sorted(build_fake_skills())},
        connectors=build_fake_connectors(),
        risk_table=build_risk_table(),
        policies=build_fake_policies(),
    )


def test_FR_INT_09_the_plan_prompt_states_today_and_the_days_left(tmp_path) -> None:
    units = copy.deepcopy(load_plan_fixture("valid", "two_approaches_email_send_gated")["units"])
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps({"units": units}))])
    inputs = _inputs()
    approach = next(a for a in inputs.approaches if a["id"] == "quick")

    compile_plan(_brief(), approach, 42.5, inputs, router=build_test_router(tmp_path, provider), today=TODAY)

    prompt = _text(provider.calls[0])
    assert "Today is 2026-10-09" in prompt and "121 days from today" in prompt
