"""FR-INT-04 / FR-INT-06, INTAKE-QUALITY-1 slice 3, through the API: the deliverables question lists what
`config/deliverable_kinds.yaml` says Tilo can produce today, several may be picked in one answer, a skip keeps the
Director's guess with its assumption, and a bad kinds file stops the task before anything is stored."""

from __future__ import annotations

import tilo_planning.deliverable_kinds as kinds_module
from tilo_planning.deliverable_kinds import load_deliverable_kinds
from tilo_planning.questions import KINDS_QUESTION


def _flow(flow_factory):
    return flow_factory(["deliverables"])


def _deliverables_question(intake):
    return next(q for q in intake["questions"] if q["field"] == "deliverables")


def test_FR_INT_04_flow_the_deliverables_question_lists_the_available_kinds(flow_factory):
    intake = _flow(flow_factory).new_task()

    question = _deliverables_question(intake)

    assert question["text"] == KINDS_QUESTION
    assert question["suggested_answers"][1:] == [k.label for k in load_deliverable_kinds()]
    assert len(question["suggested_answers"]) > 3  # the cap of three is lifted for this question only


def test_FR_INT_04_flow_several_kinds_in_one_answer_become_the_deliverables(flow_factory):
    flow = _flow(flow_factory)
    intake = flow.new_task()
    labels = _deliverables_question(intake)["suggested_answers"][1:3]

    response = flow.answers(intake["task_id"], [{"field": "deliverables", "answer": "; ".join(labels)}])  # "2 and 3"

    assert response.status_code == 200, response.text
    assert [d["title"] for d in response.json()["brief"]["deliverables"]] == labels
    assert {d["format"] for d in response.json()["brief"]["deliverables"]} <= {"markdown"}
    assert flow.approaches(intake["task_id"]).status_code == 200


def test_FR_INT_04_flow_skipping_keeps_the_guess_and_records_the_assumption(flow_factory):
    flow = _flow(flow_factory)
    intake = flow.new_task()
    before = intake["brief"]["deliverables"]

    response = flow.answers(intake["task_id"], [{"field": "deliverables", "answer": None}])

    brief = response.json()["brief"]
    assert brief["deliverables"] == before
    assert brief["assumptions"][-1]["question"] == KINDS_QUESTION and brief["assumptions"][-1]["assumed"].startswith(
        "Deliverables: "
    )


def test_FR_INT_04_flow_an_answer_that_names_nothing_offered_is_asked_again(flow_factory):
    flow = _flow(flow_factory)
    task_id = flow.new_task()["task_id"]

    refused = flow.answers(task_id, [{"field": "deliverables", "answer": "Flashcards"}])

    assert refused.status_code == 422 and "does not fit" in refused.json()["detail"]
    kept = flow.store.tasks[task_id]
    assert kept.answers == {}
    ok = flow.answers(task_id, [{"field": "deliverables", "answer": load_deliverable_kinds()[0].label}])
    assert ok.status_code == 200


def test_FR_INT_04_flow_a_bad_kinds_file_stops_the_task_before_anything_is_stored(flow_factory, monkeypatch, tmp_path):
    bad = tmp_path / "kinds.yaml"
    bad.write_text("kinds: [{id: Bad}]\n", encoding="utf-8")
    monkeypatch.setattr(kinds_module, "DEFAULT_KINDS_CONFIG", bad)
    flow = _flow(flow_factory)

    response = flow.intake()

    assert response.status_code == 503 and "nothing was stored" in response.json()["detail"]
    assert flow.store.tasks == {}


def test_FR_INT_04_flow_a_kind_that_is_not_available_yet_is_refused_and_nothing_changes(flow_factory):
    flow = _flow(flow_factory)
    task_id = flow.new_task()["task_id"]

    for answer in ("Mock-test quiz", "Study plan; Past-paper links"):
        refused = flow.answers(task_id, [{"field": "deliverables", "answer": answer}])
        assert refused.status_code == 422 and "is not available yet" in refused.json()["detail"]

    assert flow.store.tasks[task_id].answers == {}
