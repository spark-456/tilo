"""LIVE22 (PRD 7.2): a run records `world.planned` once, after `budget.granted` and before `world.started`. No run wrote
it, so a page waiting for it ("Step n of m", the planning card) waited for ever on a world that was already working."""

from __future__ import annotations

from _clint2_lib import assert_stream_valid


def test_LIVE22_a_run_records_world_planned_once_before_world_started(run_flow, registry):
    run_flow.run_to_completion()

    events = assert_stream_valid(run_flow, registry)  # schema-valid, registered, strictly increasing

    types = [e["type"] for e in events]
    assert types.count("world.planned") == 1
    assert types.index("budget.granted") < types.index("world.planned") < types.index("world.started")
    planned = next(e for e in events if e["type"] == "world.planned")
    assert planned["data"]["unit_count"] >= 1
    assert planned["data"]["tier"] in {"outpost", "village", "town", "city"}
    assert planned["data"]["credits"]["min"] <= planned["data"]["credits"]["max"]
