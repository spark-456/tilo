"""CL-INT-1 / FR-INT-08 and PRD 10.1: the task's owner is the principal who created it; anyone else gets
403 or 404 on every follow-up route (answers, approaches, approve), learns nothing about the task, spends
none of its model calls and cannot grant its budget. Only the owner sets budgets.
"""

from __future__ import annotations

from _clint1_lib import FLOW_USER, OTHER_USER

CAP = 50


def _refused(response) -> bool:
    return response.status_code in (403, 404)


def test_PRD_10_1_flow_another_user_is_refused_on_every_follow_up_route(flow):
    intake = flow.new_task()
    task_id = intake["task_id"]
    answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]
    assert flow.answers(task_id, answers).status_code == 200  # the owner can use the routes
    assert flow.approaches(task_id).status_code == 200
    flow.as_user(OTHER_USER)

    responses = [
        flow.answers(task_id, answers),
        flow.approaches(task_id),
        flow.approve(task_id, "quick", CAP),
    ]

    assert all(_refused(r) for r in responses), [(r.status_code, r.text) for r in responses]
    leaked = intake["brief"]["goal"]
    assert all(leaked not in r.text for r in responses)  # the refusal does not echo the owner's brief


def test_PRD_10_1_flow_another_user_cannot_spend_the_owners_model_calls(clear_flow):
    intake = clear_flow.task_with_approaches()  # the owner's own call: 2 model calls so far
    calls = len(clear_flow.provider.calls)
    clear_flow.as_user(OTHER_USER)

    assert _refused(clear_flow.approaches(intake["task_id"]))

    assert len(clear_flow.provider.calls) == calls == 2


def test_PRD_10_1_flow_another_user_cannot_grant_the_owners_budget(clear_flow):
    intake = clear_flow.task_with_approaches()
    clear_flow.as_user(OTHER_USER)

    assert _refused(clear_flow.approve(intake["task_id"], "quick", CAP))

    assert clear_flow.events(intake["world_id"], "budget.granted") == []
    clear_flow.as_user(FLOW_USER)  # the owner can still approve afterwards
    assert clear_flow.approve(intake["task_id"], "quick", CAP).status_code == 200


def test_PRD_10_1_flow_two_users_tasks_are_independent(flow_factory):
    flow = flow_factory([])
    mine = flow.task_with_approaches()
    flow.as_user(OTHER_USER)
    theirs = flow.task_with_approaches()  # their own task, created by them

    assert theirs["task_id"] != mine["task_id"] and theirs["world_id"] != mine["world_id"]
    assert flow.approve(theirs["task_id"], "quick", CAP).status_code == 200
    assert _refused(flow.approve(mine["task_id"], "quick", CAP))
    assert theirs["event"]["actor"] == OTHER_USER


def test_PRD_10_1_flow_the_grant_is_attributed_to_the_task_creator(flow_factory):
    flow = flow_factory([])
    flow.as_user(OTHER_USER)
    intake = flow.task_with_approaches()

    assert flow.approve(intake["task_id"], "quick", CAP).status_code == 200

    (event,) = flow.events(intake["world_id"], "budget.granted")
    assert event["actor"] == OTHER_USER
    assert event["authz"]["by"] == "person" and event["authz"]["ref"] == OTHER_USER


def test_FR_INT_08_flow_world_events_keep_strictly_increasing_seq(clear_flow):
    intake = clear_flow.task_with_approaches()
    assert clear_flow.approve(intake["task_id"], "quick", CAP).status_code == 200

    seqs = [e["seq"] for e in clear_flow.events(intake["world_id"])]

    assert seqs and all(a < b for a, b in zip(seqs, seqs[1:], strict=False))
