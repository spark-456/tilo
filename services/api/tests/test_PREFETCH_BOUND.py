"""PREFETCH-BOUND: blocked scripted calls, edit bursts, saturation and replay; no network."""

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from test_FR_INT_06_approach_speed_prefetch import WAIT_S, _answered, _approach_calls, _until
from tilo_api import tasks
from tilo_api.durable_store import _task_doc, _task_from


def test_PREFETCH_BOUND_answers_do_not_wait_and_only_latest_pending_version_runs(flow):
    started, release = threading.Event(), threading.Event()
    inner = flow.provider.generate
    calls = []

    def blocked(request):
        if "approaches" in (request.response_schema or {}).get("properties", {}):
            calls.append(request)
            if len(calls) == 1:
                started.set()
                assert release.wait(WAIT_S)
        return inner(request)

    flow.provider.generate = blocked
    task_id = _answered(flow)
    assert started.wait(WAIT_S)
    with ThreadPoolExecutor(max_workers=4) as pool:
        try:
            gets = [pool.submit(flow.approaches, task_id) for _ in range(3)]
            for i in range(20):
                edit = pool.submit(flow.answers, task_id, [], brief_edits={"goal": f"Compare supplier number {i}."})
                assert edit.result(timeout=2).status_code == 200
            assert len(calls) == 1
            assert flow.store.tasks[task_id].approaches is None
            assert flow.events(flow.store.tasks[task_id].world_id, "plan.approaches_proposed") == []
        finally:
            release.set()
        responses = [f.result(timeout=WAIT_S) for f in gets]
    assert [r.status_code for r in responses] == [200] * 3
    assert len({r.text for r in responses}) == 1
    assert len(calls) == 2
    assert "Compare supplier number 19." in calls[-1].prompt
    assert len(flow.events(flow.store.tasks[task_id].world_id, "plan.approaches_proposed")) == 1
    for _ in range(5):
        assert flow.answers(task_id, []).status_code == 200
        assert flow.approaches(task_id).status_code == 200
    assert len(calls) == 2


def test_PREFETCH_BOUND_global_queue_saturation_is_bounded_and_get_can_retry(flow, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(tasks, "_PREFETCH_SLOTS", slots)
    started, release = threading.Event(), threading.Event()
    inner = flow.provider.generate

    def blocked(request):
        if "approaches" in (request.response_schema or {}).get("properties", {}):
            started.set()
            assert release.wait(WAIT_S)
        return inner(request)

    flow.provider.generate = blocked
    first = _answered(flow)
    assert started.wait(WAIT_S)
    try:
        second = _answered(flow)
        for i in range(10):
            assert flow.answers(second, [], brief_edits={"goal": f"Compare supplier number {i}."}).status_code == 200
        assert "future" not in flow.store.tasks[second].approaches_work
        assert flow.approaches(second).status_code == 503
        assert not slots.acquire(blocking=False)
    finally:
        release.set()
    assert flow.approaches(first).status_code == 200
    _until(lambda: slots._value == 1, "the released queue slot")
    assert flow.approaches(second).status_code == 200
    assert len(_approach_calls(flow)) == 2


def test_PREFETCH_BOUND_replay_after_computation_publish_failure_never_calls_again(flow, monkeypatch):
    inner = tasks._saved

    def refused(store, writer, task_id, task, parts, changes, **records):
        if "approaches" in changes and changes["approaches"] is not None:
            raise HTTPException(status_code=503, detail="Scripted write refusal")
        return inner(store, writer, task_id, task, parts, changes, **records)

    monkeypatch.setattr(tasks, "_saved", refused)
    task_id = _answered(flow)
    for _ in range(5):
        assert flow.approaches(task_id).status_code == 503
        assert flow.answers(task_id, []).status_code == 200
    assert len(_approach_calls(flow)) == 1
    assert flow.store.tasks[task_id].approaches is None
    assert flow.events(flow.store.tasks[task_id].world_id, "plan.approaches_proposed") == []
    monkeypatch.setattr(tasks, "_saved", inner)
    assert flow.approaches(task_id).status_code == 200
    assert len(_approach_calls(flow)) == 1
    assert len(flow.events(flow.store.tasks[task_id].world_id, "plan.approaches_proposed")) == 1


def test_PREFETCH_BOUND_runtime_future_is_excluded_from_durable_task_document(flow):
    task_id = _answered(flow)
    assert flow.approaches(task_id).status_code == 200
    doc = _task_doc(flow.store.tasks[task_id])
    assert "approaches_work" not in doc and "lock" not in doc
    restored = _task_from(doc)
    assert restored.approaches == flow.store.tasks[task_id].approaches
    assert restored.approaches_work == {}
