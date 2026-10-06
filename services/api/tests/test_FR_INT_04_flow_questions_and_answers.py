"""CL-INT-1 / FR-INT-04, FR-INT-03 (PRD 7.1) through `POST /intake` (questions) and
`POST /tasks/{task_id}/answers` (TiloClient.answerQuestions): at most 3 questions, each with suggested answers;
skipping records the assumption ("Assumed: ..."); every chip is editable; a bad edit changes nothing; and the
approaches wait until the questions are answered, unless there were none. Shapes: API_CL_INT_1.md.
"""

from __future__ import annotations

import pytest
from _api_contracts_lib import errors_for, load_schema

ALL_AMBIGUOUS = ["goal", "deliverables", "audience", "deadline", "constraints"]


def test_FR_INT_04_flow_clear_task_asks_no_question(clear_flow):
    body = clear_flow.new_task()

    assert body["questions"] == []


def test_FR_INT_04_flow_vague_task_asks_at_most_3_questions_with_suggested_answers(flow_factory):
    body = flow_factory(ALL_AMBIGUOUS).new_task()

    questions = body["questions"]
    assert 1 <= len(questions) <= 3
    for q in questions:
        assert set(q) >= {"field", "text", "suggested_answers"}
        assert q["text"] and q["suggested_answers"] and all(isinstance(a, str) for a in q["suggested_answers"])
    # What was not asked is recorded as an assumption with no question, never assumed silently.
    unasked = [a for a in body["brief"]["assumptions"] if a["question"] is None]
    assert len(unasked) == len(ALL_AMBIGUOUS) - len(questions)


def test_FR_INT_04_flow_answer_updates_the_brief_and_skip_records_the_assumption(flow, repo_root, registry):
    intake = flow.new_task()
    by_field = {q["field"]: q for q in intake["questions"]}
    assert set(by_field) == {"audience", "deadline"}

    response = flow.answers(
        intake["task_id"],
        [{"field": "audience", "answer": "The board"}, {"field": "deadline", "answer": None}],
    )

    assert response.status_code == 200, response.text
    brief = response.json()["brief"]
    assert brief["audience"] == "The board"
    skipped = by_field["deadline"]
    assumed = f"Deadline: {skipped['suggested_answers'][0]}"  # "Label: value", BQ-97
    assert {"question": skipped["text"], "assumed": assumed} in brief["assumptions"]
    assert not errors_for(load_schema(repo_root, "brief"), brief, registry)


def test_FR_INT_04_flow_answering_makes_no_model_call(flow):
    intake = flow.new_task()
    calls_before = len(flow.provider.calls)

    flow.answers(intake["task_id"], [{"field": q["field"], "answer": None} for q in intake["questions"]])

    assert len(flow.provider.calls) == calls_before == 1


def test_FR_INT_03_flow_brief_edits_change_the_chips(flow):
    intake = flow.new_task()
    answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]

    response = flow.answers(
        intake["task_id"],
        answers,
        brief_edits={"goal": "Compare three suppliers on price.", "constraints": ["No internal financials"]},
    )

    assert response.status_code == 200, response.text
    brief = response.json()["brief"]
    assert brief["goal"] == "Compare three suppliers on price."
    assert brief["constraints"] == ["No internal financials"]


@pytest.mark.parametrize(
    "edits",
    [{"sensitivity": "top-secret"}, {"goal": ""}, {"deliverables": []}, {"not_a_chip": "x"}],
)
def test_FR_INT_03_flow_invalid_brief_edit_is_refused_and_changes_nothing(flow, edits):
    intake = flow.new_task()
    task_id, original = intake["task_id"], intake["brief"]
    answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]

    refused = flow.answers(task_id, answers, brief_edits=edits)
    assert refused.status_code == 422, refused.text

    retry = flow.answers(task_id, answers)  # the same task, no edits: the brief is as it was
    assert retry.status_code == 200, retry.text
    for key in ("goal", "deliverables", "sensitivity", "constraints"):
        assert retry.json()["brief"][key] == original[key]


def test_FR_INT_04_flow_answer_for_a_question_that_was_not_asked_is_refused(flow):
    intake = flow.new_task()

    response = flow.answers(intake["task_id"], [{"field": "sensitivity", "answer": "public"}])

    assert response.status_code == 422, response.text


def test_FR_INT_04_flow_approaches_wait_until_the_questions_are_answered(flow):
    intake = flow.new_task()
    assert intake["questions"]

    assert flow.approaches(intake["task_id"]).status_code == 409
    assert len(flow.provider.calls) == 1  # refused before any approaches call

    answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]
    assert flow.answers(intake["task_id"], answers).status_code == 200
    assert flow.approaches(intake["task_id"]).status_code == 200


def test_FR_INT_04_flow_approaches_are_allowed_at_once_when_there_were_no_questions(clear_flow):
    intake = clear_flow.new_task()

    assert intake["questions"] == []
    assert clear_flow.approaches(intake["task_id"]).status_code == 200


def test_FR_INT_04_flow_unknown_task_is_404(flow):
    real = flow.new_task()
    answers = [{"field": q["field"], "answer": None} for q in real["questions"]]
    assert flow.answers(real["task_id"], answers).status_code == 200  # the route exists

    assert flow.answers("t_does_not_exist", answers).status_code == 404
