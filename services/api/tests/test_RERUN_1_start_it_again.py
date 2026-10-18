"""RERUN-1 / HR-1: a world a restart closed with `world.failed` is started again as a NEW run of the same task, through
the approve path (same brief, same approved approach, same cap). Only the owner; a world that did not fail is a 409.
RERUN-ANY widened this from restart stops to every `world.failed`: see test_RERUN_ANY_any_failed_world.py."""

from __future__ import annotations

import copy
import threading
from typing import Any

import pytest
from _clint1_lib import Flow, brief_reply, make_spy_safety

REASON = "Tilo restarted during this run; start it again"


@pytest.fixture()
def flow(repo_root, store):
    made = Flow(repo_root, store, make_spy_safety(), copy.deepcopy(brief_reply([])))
    yield made
    made.close()


def _event(world_id: str, seq: int, type_: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"e_{world_id}_{seq}", "seq": seq, "type": type_, "world_id": world_id, "data": data}


def _approved(flow: Flow, *, end: str | None = "world.failed") -> dict[str, Any]:
    """An approved task whose run was stopped by a restart (or never ended, or completed)."""
    intake = flow.task_with_approaches()
    body = flow.approaches(intake["task_id"]).json()
    approach = body["recommended"]
    approved = flow.approve(intake["task_id"], approach, 80)
    assert approved.status_code == 200, approved.text
    world_id = intake["world_id"]
    stream = flow.store.events[world_id]
    n = len(stream)
    stream.append(_event(world_id, n + 1, "world.planned", {"tier": "village", "approach": approach, "unit_count": 1}))
    stream.append(_event(world_id, n + 2, "world.started", {}))
    if end == "world.failed":
        stream.append(_event(world_id, n + 3, "world.failed", {"reason": REASON, "unit": None}))
    elif end == "world.paused":
        stream.append({**_event(world_id, n + 3, "unit.completed", {}), "summary": "The first source was checked."})
        stream.append(_event(world_id, n + 4, "world.paused", {"reason": "pause_all"}))
        flow.store.worlds[world_id].paused = True
    elif end == "world.completed":
        stream.append(_event(world_id, n + 3, "world.completed", {"credits_used": 1, "deliverable_count": 1}))
    return {**intake, "approach": approach}


def test_RERUN_1_the_owner_starts_a_new_run_of_the_same_task(flow, monkeypatch):
    from tilo_api import runs

    started: list[tuple[str, str, float]] = []
    monkeypatch.setattr(
        runs,
        "start_run",
        lambda store, task, *, approach, budget_cap, seams: started.append((task.world_id, approach["id"], budget_cap)),
    )
    flow.app.dependency_overrides[runs.run_seams] = lambda: object()
    old = _approved(flow)

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 200, response.text
    new_world = response.json()["world_id"]
    assert new_world != old["world_id"]
    task = flow.store.tasks[response.json()["task_id"]]
    assert task.world_id == new_world and task.granted
    assert task.brief == flow.store.tasks[old["task_id"]].brief
    assert flow.store.worlds[new_world].owner == flow.store.worlds[old["world_id"]].owner
    grants = flow.events(new_world, "budget.granted")
    assert [g["data"]["cap"] for g in grants] == [80.0]  # the cap the person granted, decided again by the engine
    assert started[-1] == (new_world, old["approach"], 80.0)
    assert [e["type"] for e in flow.events(old["world_id"])].count("world.failed") == 1  # the old world is untouched


def test_RERUN_1_pressing_twice_is_one_new_world(flow):
    old = _approved(flow)

    first = flow.client.post(f"/worlds/{old['world_id']}/rerun")
    second = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(flow.events(first.json()["world_id"], "budget.granted")) == 1


def test_R_RUN_paused_world_continues_in_a_new_run_with_recorded_context(flow, monkeypatch):
    from tilo_api import runs

    started = []
    monkeypatch.setattr(runs, "start_run", lambda _store, task, **_kw: started.append(task.world_id))
    flow.app.dependency_overrides[runs.run_seams] = lambda: object()
    old = _approved(flow, end="world.paused")
    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")
    assert response.status_code == 200, response.text
    new = flow.store.tasks[response.json()["task_id"]]
    assert new.world_id != old["world_id"] and started[-1] == new.world_id
    assert new.brief["goal"] == flow.store.tasks[old["task_id"]].brief["goal"]
    assert any("The first source was checked." in line for line in new.brief["constraints"])
    assert flow.store.worlds[old["world_id"]].paused is True


def test_R_RUN_2_paused_continue_starts_a_new_run_from_the_brief_and_completes(run_flow):
    from _clint2_lib import wait_for  # noqa: PLC0415

    run_flow.runner.block_on = "U2"
    run_flow.start()
    approving = threading.Thread(target=run_flow.approve)
    approving.start()
    try:
        assert run_flow.runner.entered.wait(8), "the first run never reached U2"
        assert run_flow.pause().status_code in (200, 202)
        wait_for(lambda: run_flow.events("world.paused"), what="the first run to pause")
    finally:
        run_flow.runner.release.set()
        approving.join(10)

    old_world = run_flow.world_id
    continued = run_flow.flow.client.post(f"/worlds/{old_world}/rerun")
    assert continued.status_code == 200, continued.text
    run_flow.task_id = continued.json()["task_id"]
    run_flow.world_id = continued.json()["world_id"]
    run_flow.as_member()
    requested = wait_for(lambda: run_flow.events("approval.requested"), what="the continued run's approval")[0]
    cards = wait_for(lambda: run_flow.cards().json() if run_flow.cards().status_code == 200 else None, what="gate")
    card = next(card for card in cards if card["id"] == requested["data"]["card_id"])
    assert run_flow.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="the continued run to complete")
    continued_task = run_flow.store.tasks[run_flow.task_id]
    assert continued_task.brief["goal"]
    assert run_flow.world_id != old_world


def test_RERUN_1_another_user_gets_the_unknown_world_404(flow):
    old = _approved(flow)
    flow.as_user("u_someone_else")

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 404
    assert flow.client.post("/worlds/w_nothing_here/rerun").status_code == 404


@pytest.mark.parametrize("end", [None, "world.completed"])
def test_RERUN_1_a_world_that_did_not_fail_is_a_409(flow, end):
    old = _approved(flow, end=end)

    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")

    assert response.status_code == 409
    assert len([w for w in flow.store.worlds if w != old["world_id"]]) == 0  # no new world was made


@pytest.mark.parametrize(
    "latest", ["world.resumed", "world.started", "world.paused", "world.completed", "world.planned"]
)
def test_RERUN_UI_a_later_world_event_supersedes_the_restart_stop(flow, latest):
    old = _approved(flow)
    stream = flow.store.events[old["world_id"]]
    stream.append(_event(old["world_id"], len(stream) + 1, latest, {}))
    before = set(flow.store.worlds)
    response = flow.client.post(f"/worlds/{old['world_id']}/rerun")
    assert response.status_code == 409
    assert set(flow.store.worlds) == before
