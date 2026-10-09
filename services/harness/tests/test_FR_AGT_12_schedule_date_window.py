"""FR-AGT-12 (INTAKE-QUALITY-1, live run of 9 Oct 2026): a plan for a Feb 2027 exam came back as a 24-month roadmap
starting March 2025. The Verifier now runs a DETERMINISTIC date-window check, in code, before any model verifier call:
a date in a deliverable's schedule text that is before today or after the brief's deadline fails the unit's
verification, quoting the date. Only the forms listed in `schedule_dates.RECOGNISED_FORMS` are read."""

from __future__ import annotations

import asyncio
from datetime import date

from agt_scripted import ScriptedProvider
from tilo_harness.executor import DefaultUnitRunner, UnitContext
from tilo_harness.schedule_dates import RECOGNISED_FORMS, date_window_verdict, out_of_window

TODAY = date(2026, 10, 9)
DEADLINE = date(2027, 2, 7)


def _quotes(text: str, deadline: date | None = DEADLINE) -> list[str]:
    return [f.quote for f in out_of_window(text, TODAY, deadline)]


def test_FR_AGT_12_iso_dates_before_today_or_after_the_deadline_are_found() -> None:
    assert _quotes("Start 2025-03-01, mock test 2026-12-01, exam 2027-02-07, revision 2027-03-15") == [
        "2025-03-01",
        "2027-03-15",
    ]


def test_FR_AGT_12_month_and_year_is_judged_by_its_month() -> None:
    assert _quotes("March 2025: basics. Mar 2025 again.") == ["March 2025", "Mar 2025"]
    # the current month and the deadline's month are inside the window, even though some of their days are not
    assert _quotes("October 2026 and Oct 2026 and February 2027 and Feb 2027") == []
    assert _quotes("Sept 2026 is last month; March 2027 is after the exam") == ["Sept 2026", "March 2027"]


def test_FR_AGT_12_day_month_year_and_month_day_year_forms() -> None:
    assert _quotes("Week of 3 Nov 2026, week of 3rd November 2026, 5 Jan 2027") == []
    assert _quotes("Week of 3 Mar 2025 and Mar 3, 2025 and March 3rd 2025 and 8 Feb 2027 and Feb 8, 2027") == [
        "3 Mar 2025",
        "Mar 3, 2025",
        "March 3rd 2025",
        "8 Feb 2027",
        "Feb 8, 2027",
    ]
    assert _quotes("9 Oct 2026 and Oct 9, 2026 are today") == []
    assert _quotes("8 Oct 2026") == ["8 Oct 2026"]  # yesterday


def test_FR_AGT_12_without_a_deadline_only_the_past_is_checked() -> None:
    assert _quotes("2025-03-01 and 2031-01-01", deadline=None) == ["2025-03-01"]


def test_FR_AGT_12_other_forms_are_not_checked() -> None:
    text = "01/03/2025, 1.3.2025, 2025, Q1 2025, spring 2025, Week 3, in 18 months, March, 31 Feb 2025, 2025-02-30"
    assert _quotes(text) == []
    assert any("not checked" in line.lower() or "other" in line.lower() for line in RECOGNISED_FORMS)


def test_FR_AGT_12_a_date_range_is_read_date_by_date() -> None:
    assert _quotes("Mar 2025 - Jan 2027") == ["Mar 2025"]


def test_FR_AGT_12_the_verdict_is_fail_and_quotes_the_dates() -> None:
    verdict = date_window_verdict("Roadmap starts March 2025 and ends 2027-06-01.", TODAY, DEADLINE)

    assert verdict is not None
    first, _, rest = verdict.partition("\n")
    assert first == "FAIL"
    assert '"March 2025"' in rest and "before today (2026-10-09)" in rest
    assert '"2027-06-01"' in rest and "after the deadline (2027-02-07)" in rest


def test_FR_AGT_12_a_clean_schedule_has_no_verdict() -> None:
    assert date_window_verdict("Week of 3 Nov 2026: algorithms. Exam 2027-02-07.", TODAY, DEADLINE) is None
    assert date_window_verdict("", TODAY, DEADLINE) is None


def test_FR_AGT_12_the_verdict_lists_at_most_five_dates_and_a_huge_text_is_bounded() -> None:
    verdict = date_window_verdict(" ".join(f"2025-01-{d:02d}" for d in range(1, 29)), TODAY, DEADLINE)
    assert verdict is not None and verdict.count("2025-01-") == 5 and "more" in verdict
    assert out_of_window("x" * 5_000_000 + " 2025-01-01", TODAY, DEADLINE) == []  # past the scanned prefix


# --- the default unit runner: the check runs before the verifier model ---------------------------------------------

BRIEF = {"goal": "g", "audience": "a", "deliverables": [], "constraints": [], "deadline": DEADLINE.isoformat()}
VERIFY = {"id": "U2", "role": "verifier", "title": "Verify the plan", "unit_type": "verify"}


def _verify(work: str, model: ScriptedProvider):
    from tilo_harness.unit_prompt import UpstreamItem

    runner = DefaultUnitRunner({"verifier": model}, clock=lambda: TODAY)
    context = UnitContext("A_verifier", (), brief=BRIEF, upstream=(UpstreamItem("U1", "Draft", work, ()),))
    outcome = asyncio.run(runner.run(VERIFY, context))
    return outcome, outcome.outputs[0].content.decode("utf-8")


def test_FR_AGT_12_the_default_runner_fails_a_verifier_unit_without_a_model_call() -> None:
    model = ScriptedProvider({})
    outcome, text = _verify("Plan: start March 2025, exam 2027-02-07.", model)

    assert text.splitlines()[0] == "FAIL" and '"March 2025"' in text
    assert outcome.success and "Verdict: FAIL" in outcome.summary  # the verdict is the result; the unit itself ran
    assert model.prompts == [] and model.misses == []


def test_FR_AGT_12_the_default_runner_asks_the_model_when_the_dates_are_in_the_window() -> None:
    model = ScriptedProvider({"Verify the plan": "PASS\nAll good."})
    _, text = _verify("Plan: start 2026-11-02, exam 2027-02-07.", model)

    assert text.startswith("PASS") and len(model.prompts) == 1


def test_FR_AGT_12_the_verifier_prompt_states_today_and_the_deadline() -> None:
    model = ScriptedProvider({"Verify the plan": "PASS\nok"})
    _verify("No dates here.", model)

    (prompt,) = model.prompts
    assert "2026-10-09" in prompt and "2027-02-07" in prompt and "121 days from today" in prompt


def test_FR_AGT_12_only_a_verifier_unit_gets_the_pre_check() -> None:
    specialist = ScriptedProvider({"Draft the plan": "Start March 2025."})
    runner = DefaultUnitRunner({"specialist": specialist}, clock=lambda: TODAY)
    unit = {"id": "U1", "role": "specialist", "title": "Draft the plan", "unit_type": "draft"}
    outcome = asyncio.run(runner.run(unit, UnitContext("A_s", (), brief=BRIEF)))

    assert outcome.outputs[0].content == b"Start March 2025." and len(specialist.prompts) == 1


def test_FR_AGT_12_specialist_and_writer_prompts_state_today_and_the_deadline() -> None:
    for role in ("specialist", "writer"):
        model = ScriptedProvider({"Plan it": "done"})
        runner = DefaultUnitRunner({role: model}, clock=lambda: TODAY)
        unit = {"id": "U1", "role": role, "title": "Plan it", "unit_type": "draft"}
        asyncio.run(runner.run(unit, UnitContext("A_w", (), brief=BRIEF)))

        (prompt,) = model.prompts
        assert "Today is 2026-10-09. The deadline is 2027-02-07 (121 days from today)" in prompt
