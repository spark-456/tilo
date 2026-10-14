"""APPROACH-SPEED (LIVE-QA row 12, FR-INT-06): the approaches are proposed in the background as soon as the answers are
saved, with the same single model call, cached per task and brief version. GET returns the cached result or waits on
the in-flight one; a changed brief recomputes once; nothing is shared across tasks or owners. Replay and scripted
providers only: no paid call.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

WAIT_S = 10.0


def _approach_calls(flow) -> list[Any]:
    return [c for c in flow.provider.calls if "approaches" in (c.response_schema or {}).get("properties", {})]


def _until(predicate, what: str) -> None:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(f"timed out waiting for {what}")


def _answered(flow, **kwargs) -> str:
    intake = flow.new_task()
    answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]
    assert answers, intake
    assert flow.answers(intake["task_id"], answers, **kwargs).status_code == 200
    return intake["task_id"]


def test_FR_INT_06_prefetch_proposes_once_per_brief_and_get_returns_the_stored_result(flow):
    task_id = _answered(flow)

    _until(lambda: flow.store.tasks[task_id].approaches is not None, "the background approaches")
    first = flow.approaches(task_id)
    second = flow.approaches(task_id)

    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json()
    assert len(_approach_calls(flow)) == 1  # the answers' prefetch was the one call; the GETs only read it
    assert len(flow.events(flow.store.tasks[task_id].world_id, "plan.approaches_proposed")) == 1


def test_FR_INT_06_concurrent_gets_wait_on_the_one_inflight_call(flow):
    release, started = threading.Event(), threading.Event()
    inner = flow.provider.generate

    def slow(request):
        if "approaches" in (request.response_schema or {}).get("properties", {}):
            started.set()
            assert release.wait(WAIT_S), "the test never released the approaches call"
        return inner(request)

    flow.provider.generate = slow
    task_id = _answered(flow)
    assert started.wait(WAIT_S), "the answers did not start the approaches call"

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(flow.approaches, task_id) for _ in range(4)]
        time.sleep(0.2)  # every GET is now waiting on the task's lock, behind the one in-flight call
        assert not any(f.done() for f in futures)
        release.set()
        responses = [f.result(timeout=WAIT_S) for f in futures]

    assert [r.status_code for r in responses] == [200] * 4
    assert len({r.text for r in responses}) == 1
    assert len(_approach_calls(flow)) == 1


def test_FR_INT_06_a_get_before_the_prefetch_runs_still_costs_one_call(flow):
    task_id = _answered(flow)

    response = flow.approaches(task_id)  # may race the background job; either way one call in total

    assert response.status_code == 200, response.text
    time.sleep(0.3)  # the background job has been through the task's lock by now: it finds the stored result
    assert len(_approach_calls(flow)) == 1


def test_FR_INT_06_a_changed_brief_recomputes_once(flow):
    task_id = _answered(flow)
    _until(lambda: flow.store.tasks[task_id].approaches is not None, "the first approaches")
    assert len(_approach_calls(flow)) == 1

    edited = flow.answers(task_id, [], brief_edits={"goal": "Compare three suppliers on landed price."})
    assert edited.status_code == 200, edited.text
    _until(lambda: len(_approach_calls(flow)) == 2, "the recompute for the new brief")
    _until(lambda: flow.store.tasks[task_id].approaches is not None, "the second approaches")
    response = flow.approaches(task_id)

    assert response.status_code == 200, response.text
    assert len(_approach_calls(flow)) == 2  # one per brief version
    assert "Compare three suppliers on landed price." in _approach_calls(flow)[-1].prompt


def test_FR_INT_06_an_unchanged_resubmit_does_not_call_again(flow):
    task_id = _answered(flow)
    _until(lambda: flow.store.tasks[task_id].approaches is not None, "the approaches")

    again = flow.answers(task_id, [{"field": q.field, "answer": None} for q in flow.store.tasks[task_id].questions])

    assert again.status_code == 200, again.text
    assert flow.store.tasks[task_id].approaches is not None  # the cache survived the save
    assert flow.approaches(task_id).status_code == 200
    assert len(_approach_calls(flow)) == 1


def test_FR_INT_06_no_prefetch_while_a_question_is_unanswered(flow):
    intake = flow.new_task()
    first = intake["questions"][0]["field"]

    assert flow.answers(intake["task_id"], [{"field": first, "answer": None}]).status_code == 200
    time.sleep(0.2)

    assert _approach_calls(flow) == []
    assert flow.approaches(intake["task_id"]).status_code == 409


def test_FR_INT_06_the_cache_never_crosses_tasks_or_owners(flow):
    mine = _answered(flow)
    _until(lambda: flow.store.tasks[mine].approaches is not None, "my approaches")
    flow.as_user("u_someone_else")
    theirs = _answered(flow)
    _until(lambda: flow.store.tasks[theirs].approaches is not None, "their approaches")
    assert len(_approach_calls(flow)) == 2  # each task proposed for its own brief

    assert flow.approaches(mine).status_code == 404  # not their task: no oracle, no call
    flow.as_user("u_flow_owner")
    assert flow.approaches(theirs).status_code == 404
    assert len(_approach_calls(flow)) == 2
    assert flow.store.tasks[mine].approaches is not flow.store.tasks[theirs].approaches
