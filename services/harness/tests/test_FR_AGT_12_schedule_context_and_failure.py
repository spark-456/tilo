"""FR-AGT-12, INTAKE-QUALITY-1 review fixes.

1. A date BEFORE today fails only in schedule-like context: a cited past date ("Published 3 March 2019", "Smith 2019,
   12 March 2019") passes; "Week 1 (3 March 2025): start" fails. A date AFTER the deadline fails anywhere.
2. The date-window FAIL is carried by the existing unit-failure path: the verifier unit returns `success=False`, so the
   run's `failed` list holds it and its dependents are skipped (nothing is delivered)."""

from __future__ import annotations

from datetime import date

from agt_output_support import run_units
from agt_scripted import ScriptedProvider
from tilo_harness.executor import DefaultUnitRunner
from tilo_harness.schedule_dates import out_of_window

TODAY = date(2026, 10, 9)
DEADLINE = date(2027, 2, 7)


def _quotes(*lines: str, deadline: date | None = DEADLINE) -> list[str]:
    return [f.quote for f in out_of_window("\n".join(lines), TODAY, deadline)]


def test_FR_AGT_12_a_cited_past_date_passes() -> None:
    assert _quotes("Smith 2019, 12 March 2019") == []
    assert _quotes("Published 3 March 2025") == []
    assert _quotes("Sept. 3, 2026 was the release of the paper") == []
    assert _quotes("Accessed 12 Jan 2026 (source: the syllabus page)") == []
    assert _quotes("Read the 2025 survey (Patel et al., 2025) before the first week of November 2026") == []
    assert (
        _quotes("Revise from the notes published 3 March 2025: start week 1") == []
    )  # a citation cue exempts the line


def test_FR_AGT_12_a_past_date_in_a_schedule_line_fails() -> None:
    assert _quotes("Week 1 (3 March 2025): start with the basics") == ["3 March 2025"]
    assert _quotes("Phase 1 begins in March 2025") == ["March 2025"]
    assert _quotes("Finish the first pass by 3 Sept 2026") == ["3 Sept 2026"]
    assert _quotes("Mock test due 1 Oct 2026") == ["1 Oct 2026"]
    assert _quotes("Revise from 2025-11-01 to 2026-12-01") == ["2025-11-01"]
    assert _quotes("Submit by 8 Oct 2026") == ["8 Oct 2026"]  # "by" right before the date is a schedule cue


def test_FR_AGT_12_a_schedule_table_is_read_row_by_row() -> None:
    table = ["| Week | Date | Topic |", "|------|------|-------|", "| 1 | 3 March 2025 | Algorithms |"]
    assert _quotes(*table) == ["3 March 2025"]
    refs = ["| Author | Published | Title |", "|---|---|---|", "| Smith | 3 March 2019 | A survey |"]
    assert _quotes(*refs) == []  # a reference table has no schedule cue


def test_FR_AGT_12_a_line_without_a_schedule_cue_is_not_read_for_past_dates() -> None:
    assert _quotes("The syllabus changed on 12 March 2019.") == []
    assert _quotes("March 2025") == []


def test_FR_AGT_12_a_date_after_the_deadline_fails_wherever_it_stands() -> None:
    assert _quotes("Published 3 March 2031") == ["3 March 2031"]
    assert _quotes("The syllabus changes on 12 March 2031.") == ["12 March 2031"]
    assert _quotes("Smith 2031, 12 March 2031") == ["12 March 2031"]


def test_FR_AGT_12_dates_equal_to_today_or_the_deadline_pass() -> None:
    assert _quotes("Start 2026-10-09, exam 2027-02-07") == []
    assert _quotes("Start 9 Oct 2026, exam 7 Feb 2027") == []
    assert _quotes("Start Oct 9, 2026, exam Feb 7, 2027") == []
    assert _quotes("Start October 2026, exam February 2027") == []


def test_FR_AGT_12_may_the_word_is_not_a_month() -> None:
    assert _quotes("Start: you may 2026 times see this") == []
    assert _quotes("Start May 2026") == ["May 2026"]  # a capital M and a year: the month


# --- the unit fails, the run's result shows it, the dependents are skipped ------------------------------------------

BRIEF = {"goal": "g", "audience": "a", "deliverables": [], "constraints": [], "deadline": DEADLINE.isoformat()}


class _VerifierAsU2(DefaultUnitRunner):
    """The plan's U2 is a verifier-role unit; the layout of this rig has specialist-rank workers only, so the runner
    presents U2 to the default runner as the verifier it is."""

    async def run(self, unit, context):
        return await super().run({**unit, "role": "verifier"} if unit["id"] == "U2" else unit, context)


def _run(tmp_path, work: str, verifier: ScriptedProvider):
    specialist = ScriptedProvider({"Unit U1": work, "Unit U3": "delivered"})
    runner = _VerifierAsU2({"specialist": specialist, "verifier": verifier}, clock=lambda: TODAY)
    ran = run_units(
        tmp_path,
        {"U1": None, "U2": None, "U3": None},
        depends={"U2": ["U1"], "U3": ["U2"]},
        runner=runner,
        run_kwargs={"brief": BRIEF, "intake_answers": []},
    )
    return ran, specialist


def test_FR_AGT_12_a_date_window_fail_is_a_failed_unit_and_its_dependents_are_skipped(tmp_path) -> None:
    verifier = ScriptedProvider({})
    ran, specialist = _run(tmp_path, "Roadmap: start March 2025, exam 2027-02-07.", verifier)

    result = ran.result
    assert result.failed == ["U2"] and result.skipped == ["U3"]
    assert result.outcomes["U1"].success is True and result.outcomes["U2"].success is False
    assert '"March 2025"' in result.outcomes["U2"].summary and '"March 2025"' in (result.outcomes["U2"].reason or "")
    assert verifier.prompts == [] and not any("Unit U3" in p for p in specialist.prompts)  # no model call, no U3


def test_FR_AGT_12_a_schedule_inside_the_window_runs_the_model_verifier_and_the_rest(tmp_path) -> None:
    verifier = ScriptedProvider({"Unit U2": "PASS\nfine"})
    ran, _ = _run(tmp_path, "Roadmap: start 2026-11-02, exam 2027-02-07.", verifier)

    assert ran.result.failed == [] and ran.result.skipped == [] and len(verifier.prompts) == 1


def test_FR_AGT_12_a_cited_past_date_in_the_work_does_not_fail_the_unit(tmp_path) -> None:
    verifier = ScriptedProvider({"Unit U2": "PASS\nfine"})
    ran, _ = _run(tmp_path, "Roadmap: start 2026-11-02. Source: Smith 2019, published 12 March 2019.", verifier)

    assert ran.result.failed == [] and len(verifier.prompts) == 1
