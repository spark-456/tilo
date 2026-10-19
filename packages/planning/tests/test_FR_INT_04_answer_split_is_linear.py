"""FR-INT-04 (PRD 7.1), review of PR #664: the deliverables answer split was quadratic on a long run of whitespace
(20,000 spaces took 33 s) and `apply_answer` had no length limit of its own. The answer is clipped to the answers
route's 300 characters inside `_answer_formats` and split on the separators alone. No model call, no network.
"""

from __future__ import annotations

import time
from datetime import date

import pytest
from _planning_contracts_lib import load_brief_fixture, make_no_memory, sample_event_base
from tilo_planning.brief import BriefValidationError, complete_brief
from tilo_planning.questions import apply_answer, generate_questions

TODAY = date(2026, 10, 8)


def _brief_and_question() -> tuple[dict, object]:
    brief = load_brief_fixture("valid_pdf_report")
    brief["deliverables"] = [{"title": "Item 1", "format": "pdf"}]
    brief = complete_brief(brief)
    question = generate_questions(
        brief, ["deliverables"], memory=make_no_memory(), base=sample_event_base(), seq=2
    ).questions[0]
    return brief, question


@pytest.mark.parametrize("answer", [" " * 100_000, "and,;" * 20_000], ids=["spaces", "separators"])
def test_FR_INT_04_a_huge_answer_is_clipped_and_refused_fast(answer: str) -> None:
    brief, question = _brief_and_question()

    started = time.perf_counter()
    with pytest.raises(BriefValidationError):
        apply_answer(brief, question, answer, today=TODAY)  # type: ignore[arg-type]
    assert time.perf_counter() - started < 1.0


def test_FR_INT_04_text_past_the_answer_limit_is_not_read() -> None:
    brief, question = _brief_and_question()

    result = apply_answer(brief, question, "xlsx" + " " * 400 + "; docx", today=TODAY)  # type: ignore[arg-type]

    assert [d["format"] for d in result["deliverables"]] == ["xlsx"], "'docx' sits past the route's 300 characters"
