"""FR-INT-03 / FR-INT-04, INTAKE-QUALITY-1 slice 2, through the API: the Director's task-specific questions come back
from `POST /intake` as `{field: topic_N, text, suggested_answers}` (at most 3 in all), replace the generic format and
rules questions, and `POST /tasks/{id}/answers` records answers and skips as `Label: value` constraints with the
existing 300-character clip, safety screening and re-ask behaviour. The model's question text and suggested answers are
screened before they enter the brief."""

from __future__ import annotations

from _clint1_lib import INJECTION_PHRASE

TOPIC = [
    {
        "label": "Branch",
        "text": "Which branch is the exam for?",
        "suggested_answers": ["CS", "EC", "ME"],
        "expected_change": 0.9,
    },
    {
        "label": "Level",
        "text": "How far along are you?",
        "suggested_answers": ["beginner", "some revision"],
        "expected_change": 0.8,
    },
    {
        "label": "Hours per day",
        "text": "How many hours a day?",
        "suggested_answers": ["3", "5"],
        "expected_change": 0.6,
    },
    {
        "label": "Practice",
        "text": "Do you want practice material?",
        "suggested_answers": ["yes", "no"],
        "expected_change": 0.4,
    },
]


def _topic_flow(flow_factory, questions=TOPIC, ambiguous=("deliverables", "constraints", "audience")):
    flow = flow_factory(list(ambiguous))
    flow.provider.brief["questions"] = questions
    return flow


def test_FR_INT_04_flow_the_directors_questions_replace_the_generic_ones_and_stay_within_three(flow_factory):
    flow = _topic_flow(flow_factory)

    intake = flow.new_task()

    assert [q["field"] for q in intake["questions"]] == ["topic_1", "topic_2", "topic_3"]
    first = intake["questions"][0]
    assert set(first) == {"field", "text", "suggested_answers"}
    assert first["text"] == "Which branch is the exam for?" and first["suggested_answers"] == ["CS", "EC", "ME"]
    assert "questions" not in intake["brief"]  # the brief keeps the contract's shape


def test_FR_INT_04_flow_other_ambiguous_fields_fill_only_the_slots_left(flow_factory):
    flow = _topic_flow(flow_factory, TOPIC[:1])

    intake = flow.new_task()

    assert [q["field"] for q in intake["questions"]] == ["topic_1", "audience"]  # deliverables and rules are replaced


def test_FR_INT_04_flow_without_director_questions_the_generic_ones_are_asked(flow_factory):
    flow = _topic_flow(flow_factory, [])

    intake = flow.new_task()

    assert [q["field"] for q in intake["questions"]] == ["deliverables", "audience", "constraints"]


def test_FR_INT_04_flow_answers_and_skips_become_label_value_constraints_the_plan_sees(flow_factory):
    flow = _topic_flow(flow_factory)
    intake = flow.new_task()
    answers = [
        {"field": "topic_1", "answer": "CS"},
        {"field": "topic_2", "answer": None},
        {"field": "topic_3", "answer": "4, evenings only"},
    ]

    response = flow.answers(intake["task_id"], answers)

    assert response.status_code == 200, response.text
    brief = response.json()["brief"]
    assert brief["constraints"][-3:] == ["Branch: CS", "Level: beginner", "Hours per day: 4, evenings only"]
    assert {"question": "How far along are you?", "assumed": "Level: beginner"} in brief["assumptions"]
    approaches = flow.approaches(intake["task_id"])
    assert approaches.status_code == 200, approaches.text
    sent = flow.provider.calls[-1].prompt
    assert "Branch: CS" in sent and "Level: beginner" in sent


def test_FR_INT_04_flow_all_topic_questions_must_be_answered_or_skipped_before_approaches(flow_factory):
    flow = _topic_flow(flow_factory)
    intake = flow.new_task()
    assert flow.answers(intake["task_id"], [{"field": "topic_1", "answer": "CS"}]).status_code == 200

    assert flow.approaches(intake["task_id"]).status_code == 409


def test_FR_INT_04_flow_only_the_asked_ids_are_accepted_once_each(flow_factory):
    flow = _topic_flow(flow_factory)
    task_id = flow.new_task()["task_id"]

    for bad in (
        [{"field": "deliverables", "answer": "A PDF report"}],  # replaced by the Director's questions: not asked
        [{"field": "topic_4", "answer": "x"}],
        [{"field": "topic_1", "answer": "CS"}, {"field": "topic_1", "answer": "EC"}],
    ):
        assert flow.answers(task_id, bad).status_code == 422


def test_FR_INT_04_flow_the_answer_clip_and_the_re_ask_still_hold(flow_factory):
    flow = _topic_flow(flow_factory)
    task_id = flow.new_task()["task_id"]

    assert flow.answers(task_id, [{"field": "topic_1", "answer": "x" * 301}]).status_code == 422  # 300-character clip
    refused = flow.answers(task_id, [{"field": "topic_1", "answer": "<>"}])  # nothing left once cleaned
    assert refused.status_code == 422 and "does not fit" in refused.json()["detail"]
    assert flow.answers(task_id, [{"field": "topic_1", "answer": "CS"}]).status_code == 200  # asked again, answered
    assert flow.store.tasks[task_id].brief["constraints"][-1] == "Branch: CS"


def test_FR_INT_04_flow_a_typed_answer_is_screened_like_any_other_brief_string(flow_factory):
    flow = _topic_flow(flow_factory)
    task_id = flow.new_task()["task_id"]

    response = flow.answers(task_id, [{"field": "topic_1", "answer": f"{INJECTION_PHRASE} and more"}])

    assert response.status_code == 422
    assert flow.store.tasks[task_id].answers == {}


def test_FR_INT_04_flow_a_flagged_director_suggestion_cannot_enter_the_brief_by_a_skip(flow_factory):
    poisoned = [{**TOPIC[0], "suggested_answers": [f"{INJECTION_PHRASE} now", "EC"]}, *TOPIC[1:3]]
    flow = _topic_flow(flow_factory, poisoned)
    task_id = flow.new_task()["task_id"]

    skipped = flow.answers(task_id, [{"field": "topic_1", "answer": None}])

    assert skipped.status_code == 422
    assert flow.store.tasks[task_id].answers == {} and flow.store.tasks[task_id].brief["constraints"] == []
    chosen = flow.answers(task_id, [{"field": "topic_1", "answer": "EC"}])  # a safe suggestion still works
    assert chosen.status_code == 200 and chosen.json()["brief"]["constraints"][-1] == "Branch: EC"


def test_FR_INT_04_flow_the_directors_questions_survive_the_durable_store():
    from tilo_api.deps import TaskRecord
    from tilo_api.durable_store import _task_doc, _task_from
    from tilo_planning.questions import Question

    task = TaskRecord("u", "w_1", "r_1", {}, {}, [Question("topic_1", "Which?", ("CS",), 0.9, "Branch")], 2)

    restored = _task_from(_task_doc(task))

    assert restored.questions == task.questions and restored.questions[0].label == "Branch"
