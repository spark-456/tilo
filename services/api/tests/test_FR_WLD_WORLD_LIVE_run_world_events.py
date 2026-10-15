"""WORLD-LIVE (FR-WLD-04, HR-1): a real run records what the world draws. Every unit's building is planned with the
unit's title as its name, built and completed in order, the worker walks to the Delivery Dock before its item is
recorded delivered, and the delivery's own cause chain is untouched (delivered still follows the item made)."""

from __future__ import annotations

import copy

from _api_contracts_lib import assert_valid_event
from _clint2_lib import wait_for
from test_FR_CON_10_in_app_delivery_run import start as start_run
from tilo_api.layout import build_layout


def start(run_flow):
    """The run, on the layout `build_layout` really makes (the suite's own helper layout has no dock)."""

    def real(plan, *, world_id):
        run_flow.layouts[world_id] = build_layout(plan, world_id=world_id)
        return copy.deepcopy(run_flow.layouts[world_id])

    run_flow.build_layout = real
    start_run(run_flow)


def test_FR_WLD_04_WORLD_LIVE_a_run_plans_and_completes_a_named_building_for_every_unit(run_flow, repo_root, registry):
    start(run_flow)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    layout = run_flow.layouts[run_flow.world_id]
    buildings = {b["id"]: b for lv in layout["semantic"]["levels"] for d in lv["districts"] for b in d["buildings"]}
    planned = run_flow.events("building.planned")
    worked = [b for b in buildings.values() if b["plan_units"]]
    assert [e["target"] for e in planned] == list(buildings)  # the units' buildings, the hall and the dock
    assert all(buildings[e["target"]]["name"] in e["summary"] for e in planned)  # the plan's own title, not "Workshop"
    assert {e["target"] for e in run_flow.events("building.completed")} == set(buildings)
    assert [e["target"] for e in run_flow.events("building.operational")] == [b["id"] for b in worked]
    for event in (*planned, *run_flow.events("building.completed"), *run_flow.events("agent.moved")):
        assert_valid_event(repo_root, registry, event)


def test_FR_WLD_04_WORLD_LIVE_the_worker_carries_the_item_to_the_dock_before_it_is_delivered(run_flow):
    start(run_flow)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    layout = run_flow.layouts[run_flow.world_id]
    dock = next(
        b["id"] for lv in layout["semantic"]["levels"] for d in lv["districts"] for b in d["buildings"]
        if b.get("common_type") == "delivery_dock"
    )  # fmt: skip
    (delivered,) = run_flow.events("artifact.delivered")
    carried = [e for e in run_flow.events("agent.moved") if e["target"] == dock]
    assert len(carried) == 1 and carried[0]["actor"] == delivered["actor"]
    assert carried[0]["seq"] < delivered["seq"]
    (made,) = [e for e in run_flow.events("artifact.created") if e["data"]["artifact"] == run_flow.artifact_of("U3")]
    (stamped,) = [e for e in run_flow.events("building.completed") if e["target"] == dock]
    assert stamped["cause"] == delivered["id"] and stamped["seq"] > delivered["seq"]
    assert delivered["cause"] == made["id"], "the walk adds no link between the item and its delivery (HR-1)"
