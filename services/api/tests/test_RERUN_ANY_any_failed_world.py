"""RERUN-ANY: "Start it again" works for every world whose latest world state is `world.failed`, whatever the recorded
reason (a unit that failed, a restart, none at all), through the same approve path RERUN-1 uses. Only the owner; a world
still running, waiting or finished is a 409 and nothing new is stored."""

from __future__ import annotations

import copy

import pytest
from _clint1_lib import Flow, brief_reply, make_spy_safety
from test_RERUN_1_start_it_again import _approved, _event

UNIT_FAILED = "a unit failed, so the work stopped"


@pytest.fixture()
def flow(repo_root, store):
    made = Flow(repo_root, store, make_spy_safety(), copy.deepcopy(brief_reply([])))
    yield made
    made.close()


def _failed_with(flow: Flow, reason: object) -> dict:
    old = _approved(flow)
    flow.store.events[old["world_id"]][-1]["data"]["reason"] = reason
    return old


@pytest.mark.parametrize("reason", [UNIT_FAILED, "an internal error stopped the work", "", None])
def test_RERUN_ANY_a_failed_world_reruns_for_the_owner(flow, monkeypatch, reason):
    from tilo_api import runs

    started: list[tuple[str, str, float]] = []
    monkeypatch.setattr(
        runs,
        "start_run",
        lambda store, task, *, approach, budget_cap, seams: started.append((task.world_id, approach["id"], budget_cap)),
    )
    flow.app.dependency_overrides[runs.run_seams] = lambda: object()
    old = _failed_with(flow, reason)
    before = len(started)  # the original run's start

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 200, response.text
    new_world = response.json()["world_id"]
    assert new_world != old["world_id"]
    task = flow.store.tasks[response.json()["task_id"]]
    assert task.granted
    assert task.brief["goal"] == flow.store.tasks[old["task_id"]].brief["goal"]
    assert [g["data"]["cap"] for g in flow.events(new_world, "budget.granted")] == [80.0]
    assert started[before:] == [(new_world, old["approach"], 80.0)]
    again = flow.client.post(f"/worlds/{old['world_id']}/rerun")  # pressed twice: the same one new world
    assert again.status_code == 200 and again.json() == response.json()
    assert len(started) == before + 1


def test_P0_RUN_DIES_try_again_resumes_from_the_failed_unit_and_keeps_completed_work(flow, monkeypatch):
    from tilo_api import runs

    monkeypatch.setattr(runs, "start_run", lambda *_args, **_kwargs: None)
    flow.app.dependency_overrides[runs.run_seams] = lambda: object()
    old = _failed_with(flow, "the model reply was cut off before step U2 finished")
    stream = flow.store.events[old["world_id"]]
    stream.insert(
        -1,
        {**_event(old["world_id"], len(stream), "unit.completed", {}), "summary": "U1 checked the sources."},
    )
    stream[-1]["data"]["unit"] = "U2"

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 200, response.text
    brief = flow.store.tasks[response.json()["task_id"]].brief
    assert any("U1 checked the sources." in line for line in brief["constraints"])
    assert any("U2" in line and "resume" in line.lower() for line in brief["constraints"])


def test_RUN_RESILIENCE_api_starts_again_after_transient_exhaustion_and_keeps_finished_unit(flow, monkeypatch):
    from tilo_api import runs

    started = []
    monkeypatch.setattr(
        runs, "start_run", lambda store, task, *, approach, budget_cap, seams: started.append(task.world_id)
    )
    flow.app.dependency_overrides[runs.run_seams] = lambda: object()
    old = _failed_with(flow, "no model could answer a step")
    stream = flow.store.events[old["world_id"]]
    stream.insert(
        -1, {**_event(old["world_id"], len(stream), "unit.completed", {}), "summary": "U1 finished research."}
    )
    stream[-1]["data"]["unit"] = "U2"

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun", json={})

    assert response.status_code == 200, response.text
    assert started[-1:] == [response.json()["world_id"]]
    brief = flow.store.tasks[response.json()["task_id"]].brief
    assert any("U1 finished research." in line for line in brief["constraints"])
    assert any("U2" in line for line in brief["constraints"])


def test_RERUN_ANY_a_share_change_after_the_stop_does_not_hide_it(flow):
    old = _failed_with(flow, UNIT_FAILED)
    stream = flow.store.events[old["world_id"]]
    stream.append(_event(old["world_id"], len(stream) + 1, "world.share_changed", {}))

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 200, response.text


def test_RERUN_ANY_another_user_is_refused_with_the_unknown_world_404(flow):
    old = _failed_with(flow, UNIT_FAILED)
    before = set(flow.store.worlds)
    flow.as_user("u_someone_else")

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 404
    assert set(flow.store.worlds) == before


@pytest.mark.parametrize("latest", [None, "world.started", "world.resumed", "world.paused", "world.completed"])
def test_RERUN_ANY_a_running_waiting_or_finished_world_is_a_409(flow, latest):
    old = _approved(flow, end=None)
    stream = flow.store.events[old["world_id"]]
    if latest is not None:
        stream.append(_event(old["world_id"], len(stream) + 1, latest, {}))
    before = set(flow.store.worlds)

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 409
    assert set(flow.store.worlds) == before


def test_RUN_RESILIENCE_rerun_with_an_empty_json_body_is_a_plain_rerun(flow, monkeypatch):
    """The live web sent `{}` for a plain "Start again" and got a 422 (19 Oct); `{}` now reruns like no body."""
    from tilo_api import runs

    monkeypatch.setattr(runs, "start_run", lambda store, task, *, approach, budget_cap, seams: None)
    flow.app.dependency_overrides[runs.run_seams] = lambda: object()
    old = _failed_with(flow, UNIT_FAILED)
    response = flow.client.post(f"/worlds/{old['world_id']}/rerun", json={})
    assert response.status_code == 200, response.text
    assert flow.client.post(f"/worlds/{old['world_id']}/rerun", json={"direction": "  "}).status_code in (409, 422)
