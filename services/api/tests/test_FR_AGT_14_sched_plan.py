"""FR-AGT-14 SCHED_PLAN (issue #656, BQ-DEVH-2): a scheduled run can plan.

`contracts/plan.schema.json` wants 2 to 3 `approaches`; the starter used to hand the compiler a list of ONE, so the
plan failed after the world and the budget grant existed. Now `POST /schedules` snapshots the full offered list beside
the chosen approach and the starter hands THAT to the compiler. A record without the list (made before this ticket)
is skipped cleanly (`snapshot_incomplete`) before any world or grant exists. No model call, no network.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from _clint1_lib import seam
from _clint2_lib import wait_for
from _fr_agt_14_lib import SchedApi
from test_FR_AGT_14_scheduled_start import armed, fire, run_start, settled, world_of
from tilo_api import deps
from tilo_harness.schedule import StartSkipped


@pytest.fixture
def rig(run_flow, monkeypatch) -> SchedApi:
    return SchedApi(run_flow.flow, monkeypatch, rf=run_flow)


class PlanSpy:
    """The compile seam: records the approaches the starter hands over and refuses what plan.schema.json refuses."""

    def __init__(self, rig: SchedApi) -> None:
        self.rig, self.seen = rig, []
        rig.flow.app.dependency_overrides[seam(deps, "get_plan_compiler")] = lambda: self.compile

    def compile(self, *, brief: dict, approach: dict, budget_cap: float, context: Any = None) -> dict:
        offered = copy.deepcopy(context.approaches)
        self.seen.append(offered)
        if not 2 <= len(offered) <= 3 or approach["id"] not in {a["id"] for a in offered}:
            raise ValueError("plan.schema.json: approaches minItems 2, maxItems 3, the chosen one among them")
        return self.rig.rf.compile_plan(brief=brief, approach=approach, budget_cap=budget_cap, context=context)


def offer_three(rig: SchedApi, task_id: str) -> list[dict[str, Any]]:
    task = rig.store.tasks[task_id]
    third = {**copy.deepcopy(task.approaches[0]), "id": "middle", "label": "Middle way"}
    task.approaches.append(third)
    return copy.deepcopy(task.approaches)


def test_FR_AGT_14_SCHED_PLAN_create_snapshots_the_full_offered_list(rig: SchedApi) -> None:
    source = armed(rig)
    offered = offer_three(rig, source.task_id)
    view = rig.created(source)
    record = rig.schedules.get(view["schedule_id"])
    assert [a["id"] for a in record.approaches] == ["quick", "thorough", "middle"]
    assert record.approaches == offered and record.approach == offered[0]
    assert "approaches" not in view and "approach" not in view  # the view shows no more than it did

    rig.store.tasks[source.task_id].approaches[0]["label"] = "changed after the fact"
    assert rig.schedules.get(view["schedule_id"]).approaches == offered  # a copy, not the task's list


def test_FR_AGT_14_SCHED_PLAN_a_fired_slot_plans_from_the_offered_list_and_reaches_its_run(rig: SchedApi) -> None:
    source = armed(rig)
    offer_three(rig, source.task_id)
    spy = PlanSpy(rig)
    sid = rig.created(source)["schedule_id"]
    assert fire(rig) == 1
    world_id = world_of(rig, sid)
    wait_for(lambda: rig.events(world_id, "world.started"), what="the scheduled run to start")
    stream = settled(rig, world_id)

    assert len(spy.seen) == 1 and [a["id"] for a in spy.seen[0]] == ["quick", "thorough", "middle"]
    assert "run.failed" not in {e["type"] for e in stream}
    assert rig.rf.runner.ran, "the first unit ran: the compile no longer fails after the world and grant exist"


@pytest.mark.parametrize("offered_count", [2, 3])
def test_FR_AGT_14_SCHED_PLAN_the_compiler_gets_two_to_three_approaches_with_the_chosen_one(
    rig: SchedApi, offered_count: int
) -> None:
    source = armed(rig)
    if offered_count == 3:
        offer_three(rig, source.task_id)
    spy = PlanSpy(rig)
    rig.insert(source, "sched_a")
    rig.starter().start(run_start(rig, "sched_a"))
    (seen,) = spy.seen
    assert 2 <= len(seen) <= 3 and "quick" in {a["id"] for a in seen}
    assert rig.rf.compile_calls[-1]["approach"]["id"] == "quick"  # the chosen one is still record.approach


def _incomplete(source: Any, rig: SchedApi) -> list[Any]:
    chosen = copy.deepcopy(rig.store.tasks[source.task_id].approaches[0])
    other = {**copy.deepcopy(chosen), "id": "other"}
    return [
        None,  # a record made before this ticket
        [chosen],  # one is below the schema's minimum
        [chosen, {**other, "id": "o2"}, {**other, "id": "o3"}, {**other, "id": "o4"}],  # four is above its maximum
        [other, {**other, "id": "o2"}],  # the chosen approach is not among them
        [chosen, "not a dict"],
    ]


@pytest.mark.parametrize("which", range(5))
def test_FR_AGT_14_SCHED_PLAN_an_incomplete_snapshot_is_skipped_before_any_world_or_grant(
    rig: SchedApi, which: int
) -> None:
    source = armed(rig)
    spy = PlanSpy(rig)
    rig.insert(source, "sched_a", approaches=_incomplete(source, rig)[which])
    events_before = {w: len(e) for w, e in rig.store.events.items()}
    worlds_before = set(rig.store.worlds)

    with pytest.raises(StartSkipped) as skipped:
        rig.starter().start(run_start(rig, "sched_a"))
    assert skipped.value.code == "snapshot_incomplete" and skipped.value.count is True
    assert set(rig.store.worlds) == worlds_before  # no orphan world
    assert {w: len(e) for w, e in rig.store.events.items()} == events_before  # no budget.granted, nothing written
    assert spy.seen == []


def test_FR_AGT_14_SCHED_PLAN_a_legacy_record_through_the_tick_is_recorded_not_retried_every_minute(
    rig: SchedApi,
) -> None:
    source = armed(rig)
    rig.insert(source, "sched_a", approaches=None)
    assert fire(rig) == 0
    record = rig.schedules.get("sched_a")
    assert record.last_error == "snapshot_incomplete" and rig.worlds_besides(source.world_id) == []


def test_FR_AGT_14_SCHED_PLAN_create_refuses_an_offered_list_outside_two_to_three(rig: SchedApi) -> None:
    source = armed(rig)
    task = rig.store.tasks[source.task_id]
    task.approaches = [task.approaches[0]]
    assert rig.create(source).status_code == 409
    task.approaches = [{**copy.deepcopy(task.approaches[0]), "id": f"a{i}"} for i in range(4)]
    task.approaches[0]["id"] = "quick"
    assert rig.create(source).status_code == 409
    assert rig.listing().json() == {"schedules": []}


def test_FR_AGT_14_SCHED_PLAN_create_refuses_an_oversized_approach(rig: SchedApi) -> None:
    source = armed(rig)
    rig.store.tasks[source.task_id].approaches[1]["summary"] = "x" * 100_000
    assert rig.create(source).status_code == 409
    assert rig.listing().json() == {"schedules": []}
