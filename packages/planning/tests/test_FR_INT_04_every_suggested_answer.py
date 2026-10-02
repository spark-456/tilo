"""FR-INT-04 (PRD 7.1), CL-INT-1 follow-up #139: every suggested answer of every question field either sets the
chip value it stands for, in a brief that still validates, or is refused. The goal's "Something else, which I
will describe" is a prompt, not a goal (BQ-99), and "The web as well" never turns the goal into a search query.
"""

from __future__ import annotations

from datetime import date

import pytest
from _planning_contracts_lib import load_brief_fixture, make_no_memory, sample_event_base
from tilo_planning.brief import CHIP_FIELDS, BriefValidationError, complete_brief, validate_brief
from tilo_planning.questions import DESCRIBE_GOAL, apply_answer, generate_questions

TODAY = date(2026, 10, 2)  # a Friday


def _brief() -> dict:
    brief = load_brief_fixture("valid_pdf_report")
    brief["sources"] = [{"kind": "file", "ref": "a_01", "label": "prices.pdf"}]
    return complete_brief(brief)


def _cases() -> list[tuple[str, str]]:
    cases = []
    for field in CHIP_FIELDS:
        asked = generate_questions(_brief(), [field], memory=make_no_memory(), base=sample_event_base(), seq=2)
        cases += [(field, answer) for answer in asked.questions[0].suggested_answers]
    return cases


@pytest.mark.parametrize(("field", "answer"), _cases())
def test_FR_INT_04_every_suggested_answer_validates_or_is_refused(field, answer):
    brief = _brief()
    question = generate_questions(brief, [field], memory=make_no_memory(), base=sample_event_base(), seq=2).questions[0]

    if field == "goal" and answer == DESCRIBE_GOAL:
        with pytest.raises(BriefValidationError, match="goal chip"):
            apply_answer(brief, question, answer, today=TODAY)
        return

    result = apply_answer(brief, question, answer, today=TODAY)

    assert validate_brief(result) == result
    assert DESCRIBE_GOAL not in str(result), "a prompt is never stored as a value"
    assert {k: v for k, v in result.items() if k != field} == {k: v for k, v in brief.items() if k != field}


def test_FR_INT_04_the_web_as_well_never_turns_the_goal_into_a_web_query():
    brief = _brief()
    question = generate_questions(brief, ["sources"], memory=make_no_memory(), base=sample_event_base(), seq=2)

    result = apply_answer(brief, question.questions[0], "The web as well", today=TODAY)

    web = [s for s in result["sources"] if s["kind"] == "web"]
    assert len(web) == 1
    assert brief["goal"] not in {s["ref"] for s in web}
    assert {s["ref"] for s in result["sources"] if s["kind"] == "file"} == {"a_01"}, "the files stay"
