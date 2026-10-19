"""FR-INT-03 / FR-INT-06, INTAKE-QUALITY-1: the API gives the Director today's date from its injectable clock
(`deps.get_today`), on intake and on the approaches request. A test overrides the clock with a fixed date."""

from __future__ import annotations

from datetime import date

from tilo_api import deps

FIXED = date(2026, 10, 9)


def test_FR_INT_03_flow_the_brief_and_approaches_prompts_state_the_clock_date(clear_flow):
    clear_flow.app.dependency_overrides[deps.get_today] = lambda: lambda: FIXED

    intake = clear_flow.new_task()
    clear_flow.approaches(intake["task_id"])

    brief_call, approaches_call = clear_flow.provider.calls[:2]
    assert "Today is 2026-10-09" in f"{brief_call.system or ''}\n{brief_call.prompt}"
    assert "Today is 2026-10-09" in approaches_call.prompt


def test_FR_INT_03_flow_without_an_override_the_prompt_states_the_real_date(clear_flow):
    clear_flow.new_task()

    (brief_call,) = clear_flow.provider.calls[:1]
    assert f"Today is {date.today().isoformat()}" in brief_call.prompt
