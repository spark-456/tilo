"""RERUN-2 (follow-ups of the LIVE3 security review of RERUN-1): "Start it again" retries a first start that failed,
dedupes through the durable store, refuses before it stores anything, and a task a failed commit evicted is a 404 or a
reload, never a 500. Replay providers; `DurableStore` over `MemoryBackend` for the second instance.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _clint1_lib import Flow, brief_reply, make_spy_safety
from _pw1b_lib import OWNER, T1, W1, make_rig, part, seed, task, wire, world
from _pw1b_lib import granted as granted_part
from fastapi.testclient import TestClient
from test_RERUN_1_start_it_again import _approved
from tilo_api import app, deps, runs


@pytest.fixture()
def flow(repo_root, store):
    made = Flow(repo_root, store, make_spy_safety(), copy.deepcopy(brief_reply([])))
    yield made
    made.close()


def _installed_seams(flow, monkeypatch, *, fail_first: int = 0) -> list[str]:
    """Run seams that exist, a `start_run` that fails `fail_first` times and then marks the world's run started."""
    calls: list[str] = []

    def start_run(store, task, *, approach, budget_cap, seams):
        calls.append(task.world_id)
        if len(calls) <= fail_first:
            raise RuntimeError("the start failed")
        store.runs[task.world_id] = object()

    monkeypatch.setattr(runs, "start_run", start_run)
    flow.app.dependency_overrides[runs.run_seams] = lambda: object()
    return calls


def _no_orphans(flow, old_world: str) -> None:
    assert [w for w in flow.store.worlds if w != old_world] == []
    assert [t for t, rec in flow.store.tasks.items() if rec.world_id != old_world] == []


def test_RERUN_2_a_failed_first_start_is_retried_not_answered_200(flow, monkeypatch):
    old = _approved(flow)  # the original run, approved before any of this
    monkeypatch.setattr(deps, "enforced", lambda *a, **k: True)  # deployed: a start that fails is loud
    calls = _installed_seams(flow, monkeypatch, fail_first=1)

    first = flow.client.post(f"/worlds/{old['world_id']}/rerun")
    second = flow.client.post(f"/worlds/{old['world_id']}/rerun")  # the same press again: retries only the start
    third = flow.client.post(f"/worlds/{old['world_id']}/rerun")  # now started: the one new world, no third start

    assert first.status_code == 503, first.text
    assert second.status_code == 200, second.text
    assert third.status_code == 200 and third.json() == second.json()
    assert len(calls) == 2  # the failed start and its retry; the third press started nothing
    assert len(flow.events(second.json()["world_id"], "budget.granted")) == 1  # one grant, never a second


def test_RERUN_2_a_second_instance_dedupes_through_the_durable_store():
    rig = make_rig("memory")
    stream = [
        part(
            1,
            type="world.planned",
            target=W1,
            data={"tier": "village", "approach": "quick", "unit_count": 1, "credits": {"min": 1, "max": 2}},
        ),
        part(2, type="world.started", target=W1, data={"budget_cap": 40}),
        granted_part(3, W1, 40),
        part(4, type="world.failed", target=W1, data={"reason": "the service restarted", "unit": None}),
    ]
    first_store, _ = rig.process()
    seed(first_store, worlds={W1: world()}, tasks={T1: task(granted=True)}, parts={W1: stream})
    principal = deps.Principal(user_id=OWNER, role="owner")
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
    app.dependency_overrides[runs.run_seams] = lambda: None
    try:
        wire(app, first_store)
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.post(f"/worlds/{W1}/rerun")
        assert first.status_code == 200, first.text

        second_store, _ = rig.process()  # scale to zero and back: a fresh process with an empty cache
        assert second_store.tasks == {} and second_store.worlds == {}
        wire(app, second_store)
        with TestClient(app, raise_server_exceptions=False) as client:
            second = client.post(f"/worlds/{W1}/rerun")

        assert second.status_code == 200, second.text
        assert second.json() == first.json()  # not a 409 stale
        new_world = first.json()["world_id"]
        assert [e["type"] for e in rig.stream(new_world)].count("budget.granted") == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("refusal", ["replay_only", "ceiling", "no_seams", "no_budget"])
def test_RERUN_2_a_refusal_leaves_no_orphan_world_or_task(flow, monkeypatch, request, refusal):
    old = _approved(flow)
    expected = 409
    if refusal == "replay_only":
        from tilo_metering import flags

        flags.process_flags().set("replay_only", True, reason="RERUN-2 test")
        request.addfinalizer(lambda: flags.process_flags().set("replay_only", False, reason="RERUN-2 test done"))
        expected = 503
    elif refusal == "ceiling":
        monkeypatch.setattr(deps, "budget_cap_ceiling", lambda: 10.0)
        expected = 422
    elif refusal == "no_seams":
        monkeypatch.setattr(deps, "enforced", lambda *a, **k: True)
        expected = 503
    else:  # the original grant is gone from the stream: nothing to start again with
        flow.store.events[old["world_id"]][:] = [
            e for e in flow.store.events[old["world_id"]] if e["type"] != "budget.granted"
        ]

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == expected, response.text
    _no_orphans(flow, old["world_id"])


def test_RERUN_2_an_evicted_task_is_a_404_or_a_reload_never_a_500(flow):
    intake = flow.task_with_approaches()
    approach: Any = flow.approaches(intake["task_id"]).json()["recommended"]
    del flow.store.tasks[intake["task_id"]]  # what a failed commit's eviction leaves behind, with no durable copy

    paths = [
        flow.client.post(f"/tasks/{intake['task_id']}/answers", json={"answers": [], "brief_edits": {}}),
        flow.client.get(f"/tasks/{intake['task_id']}/approaches"),
        flow.client.post(f"/tasks/{intake['task_id']}/approve", json={"approach_id": approach, "budget_cap": 10}),
    ]

    assert [r.status_code for r in paths] == [404, 404, 404], [r.text for r in paths]


def test_RERUN_2_an_evicted_task_with_a_durable_copy_is_reloaded(monkeypatch):
    from tilo_api import tasks

    rig = make_rig("memory")
    store, _ = rig.process()
    seed(store, worlds={W1: world()}, tasks={T1: task()})
    fresh, _ = rig.process()  # an empty cache; the records are in the backend
    real_owned = tasks._owned

    def owned_then_evicted(store_, task_id, principal):
        found = real_owned(store_, task_id, principal)
        store_.tasks.pop(task_id)  # a failed commit's eviction, between the owner check and the task's lock
        return found

    monkeypatch.setattr(tasks, "_owned", owned_then_evicted)
    principal = deps.Principal(user_id=OWNER, role="owner")
    app.dependency_overrides[deps.get_current_principal] = lambda: principal
    app.dependency_overrides[runs.run_seams] = lambda: None
    try:
        wire(app, fresh)
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(f"/tasks/{T1}/approve", json={"approach_id": "quick", "budget_cap": 10})
        assert response.status_code == 200, response.text
        assert T1 in fresh.tasks and fresh.tasks[T1].granted  # reloaded, then granted once
    finally:
        app.dependency_overrides.clear()
