"""FR-INT-04 (PRD 7.1): "At most 3 clarifying questions, ranked by expected change to the plan,
each with suggested answers; skipping records the assumption used." Acceptance test: "Given a
clear task, then 0 questions are asked; given a vague one, then <= 3 appear, and skipping shows
'Assumed: ...'"

Design (this ticket, since `tilo_planning` does not exist yet): `tilo_planning.brief.extract_brief`
flags *which* brief fields are ambiguous (`ExtractionResult.ambiguous_fields`) -- a judgement call,
the model's job. `tilo_planning.questions.generate_questions` turns that list into ranked, capped,
worded questions with suggested answers, entirely in deterministic code (the ticket brief:
"Ranking and the cap are deterministic code, not the model's say") -- exercised here directly on a
brief dict, decoupled from the Director role.

Public interface: `tilo_planning.questions.generate_questions`, `MAX_QUESTIONS`, `record_assumption`.

Ambiguity resolved here (CLAUDE.md: PRD's stated default): the `assumed` value stored in
`brief.schema.json`'s `assumptions[].assumed` is the raw assumed value (e.g. "No firm deadline"),
not the literal string "Assumed: ..." -- that prefix is the chip's *display* text (PRD 7.1's Given/
When/Then), added when a chip is rendered, not baked into the stored contract field.
"""

from __future__ import annotations

from _planning_contracts_lib import (
    assert_valid_brief,
    assert_valid_event,
    load_brief_fixture,
    make_no_memory,
    sample_event_base,
)
from tilo_planning.questions import MAX_QUESTIONS, generate_questions, record_assumption


def _clear_brief() -> dict:
    return load_brief_fixture("valid_pdf_report")


def test_FR_INT_04_clear_task_asks_zero_questions(repo_root, registry):
    result = generate_questions(_clear_brief(), [], memory=make_no_memory(), base=sample_event_base(), seq=2)

    assert result.questions == []
    assert result.event is None, (
        "plan.questions_asked.schema.json requires question_count >= 1 -- 0 questions means no event at all"
    )


def test_FR_INT_04_vague_task_asks_at_most_three_questions_ranked_by_expected_change(repo_root, registry):
    brief = _clear_brief()
    ambiguous_fields = ["sources", "audience", "deadline", "deliverables"]  # 4 candidates: one must be dropped

    result = generate_questions(brief, ambiguous_fields, memory=make_no_memory(), base=sample_event_base(), seq=2)

    assert len(result.questions) == MAX_QUESTIONS == 3
    changes = [q.expected_change for q in result.questions]
    assert changes == sorted(changes, reverse=True), "FR-INT-04: questions are ranked by expected change to the plan"
    for question in result.questions:
        assert question.text
        assert question.suggested_answers, "FR-INT-04: every question has suggested answers"

    assert result.event is not None
    assert result.event["type"] == "plan.questions_asked"
    assert result.event["data"]["question_count"] == 3
    assert_valid_event(repo_root, registry, result.event)


def test_FR_INT_04_skipping_a_question_records_the_assumption(repo_root, registry):
    brief = _clear_brief()
    result = generate_questions(brief, ["deadline"], memory=make_no_memory(), base=sample_event_base(), seq=2)
    question = result.questions[0]

    updated = record_assumption(result.brief, question, "No firm deadline")

    assert updated["assumptions"][-1] == {"question": question.text, "assumed": "Deadline: No firm deadline"}
    assert_valid_brief(repo_root, registry, updated)


def test_FR_INT_04_skipping_with_the_guess_leaves_the_chip_and_uses_the_label_value_form():
    brief = _clear_brief()
    result = generate_questions(brief, ["audience"], memory=make_no_memory(), base=sample_event_base(), seq=2)
    question = result.questions[0]

    skipped = record_assumption(result.brief, question)

    assert skipped["audience"] == result.brief["audience"]
    assert skipped["assumptions"][-1]["assumed"] == f"Audience: {result.brief['audience']}"
    # the same form the over-the-cap path records (BQ-97)
    over = generate_questions(
        brief, ["deliverables", "goal", "sources", "audience"], memory=make_no_memory(), base=sample_event_base(), seq=2
    )
    assert over.brief["assumptions"][-1]["assumed"].startswith("Audience: ")


def test_FR_INT_04_skipping_with_another_value_writes_it_into_the_field_it_assumes():
    brief = _clear_brief()
    result = generate_questions(brief, ["audience"], memory=make_no_memory(), base=sample_event_base(), seq=2)

    skipped = record_assumption(result.brief, result.questions[0], "An external client")

    assert skipped["audience"] == "An external client"
    assert skipped["assumptions"][-1]["assumed"] == "Audience: An external client"
