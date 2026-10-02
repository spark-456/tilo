"""CL-INT-2 / CP2 (PRD 5.4 "intake -> plan -> world -> a gated action", 7.1 FR-INT-09, 8.1, 9.4 HR-1; ADR-0008):
after `POST /tasks/{task_id}/approve` a run starts for the approved plan, and only for a plan that
`tilo_planning.plangraph.validate_plan` accepts. Routes, seams and the event sequence: API_CL_INT_2.md.

Every run here uses scripted fakes (compiler, layout builder, unit runner, mock connector): no model, no network,
no live mode.
"""

from __future__ import annotations

import pytest
from _clint2_lib import (
    BAD_PLANS,
    CAP,
    UNIT_ARTIFACT,
    bad_plan,
    base_plan,
    connector_registry,
    index_of,
    only,
    plan_violations,
    wait_for,
)

RUN_SEAMS = (
    "get_plan_compiler",
    "get_layout_builder",
    "get_unit_runner",
    "get_action_resolver",
    "get_skill_registry",
    "get_connector_registry",
    "get_connector_adapters",
    "get_outbox_store",
)


def test_CP2_the_run_seams_of_api_cl_int_2_exist():
    from tilo_api import deps

    missing = [name for name in RUN_SEAMS if not callable(getattr(deps, name, None))]
    assert not missing, f"tilo_api.deps lacks the run seams {missing} (see API_CL_INT_2.md)"


def test_CP2_the_scripted_plans_are_valid_or_invalid_as_labelled():
    """Guard for the fixtures the other tests script (the check that the 'bad' plans really are bad, so the
    'never starts' tests cannot pass by accident, and that the good plan is accepted)."""
    registry = connector_registry()
    assert plan_violations(base_plan(), registry) == []
    assert plan_violations(base_plan("thorough", 7.5), registry) == []
    for kind, rule in BAD_PLANS.items():
        found = {v.rule_id for v in plan_violations(bad_plan(kind), registry)}
        assert rule in found, (kind, found)


def test_CP2_approve_starts_a_run_for_the_validated_plan(run_flow, monkeypatch):
    run_flow.spy_validate_plan(monkeypatch)
    intake = run_flow.start()

    response = run_flow.approve()

    assert response.status_code == 200, response.text
    assert response.json() == {"world_id": run_flow.world_id}
    (started,) = wait_for(lambda: run_flow.events("world.started"), what="world.started")
    assert started["data"]["budget_cap"] == CAP
    (call,) = run_flow.compile_calls
    assert call["cap"] == CAP and call["approach"]["id"] == "quick"
    assert call["brief"]["goal"] == intake["brief"]["goal"]
    assert [c for c in run_flow.validate_calls if c["plan"] == run_flow.last_plan and c["violations"] == []]
    timeline = run_flow.timeline
    assert timeline.index("compile") < timeline.index("validate") < timeline.index("event:world.started")
    stream = run_flow.stream()
    assert index_of(stream, only(stream, "budget.granted")) < index_of(stream, started)


@pytest.mark.parametrize("kind", sorted(BAD_PLANS))
def test_CP2_a_plan_that_fails_validation_never_starts(run_flow, monkeypatch, kind):
    run_flow.spy_validate_plan(monkeypatch)
    run_flow.compile_mode = kind
    run_flow.start()

    response = run_flow.approve()

    assert response.status_code == 200, response.text  # the grant is the person's; the plan is not theirs to fix
    wait_for(lambda: run_flow.validate_calls, what="validate_plan to be called")
    assert BAD_PLANS[kind] in {v.rule_id for v in run_flow.validate_calls[0]["violations"]}
    _assert_nothing_started(run_flow)


def test_CP2_a_compiler_that_fails_never_starts_a_run_and_approve_still_answers(run_flow):
    run_flow.compile_mode = "raise"
    run_flow.start()

    response = run_flow.approve()

    assert response.status_code == 200, response.text
    wait_for(lambda: run_flow.compile_calls, what="the compiler to be called")
    _assert_nothing_started(run_flow)


def _assert_nothing_started(rf):
    events = rf.quiet_stream()
    assert len(rf.events("budget.granted")) == 1
    assert {e["type"] for e in rf.after_grant()} <= {"world.failed"}, [e["type"] for e in events]
    assert len(rf.events("world.failed")) <= 1
    assert rf.runner.ran == []
    assert rf.outbox_store.all_entries() == []
    assert rf.adapter.sent == []
    cards = rf.cards()
    assert cards.status_code in (200, 403, 404)
    if cards.status_code == 200:
        assert cards.json() == []
    assert rf.delivery().status_code == 409


def test_FR_AGT_11_a_second_approve_does_not_start_a_second_run(run_flow):
    run_flow.run_to_gate()

    again = run_flow.approve()

    assert again.status_code == 409 or (again.status_code == 200 and again.json()["world_id"] == run_flow.world_id)
    run_flow.quiet_stream()
    types = run_flow.types()
    for once in ("budget.granted", "world.started", "approval.requested"):
        assert types.count(once) == 1, (once, types)
    assert len(run_flow.compile_calls) == 1
    assert run_flow.runner.ran == ["U1", "U2", "U3", "U4"]


def test_CP2_units_run_in_dependency_order_each_with_agent_and_artifact_events(run_flow):
    requested, _ = run_flow.run_to_gate()
    events = run_flow.stream()

    assigned = {e["data"]["unit"]: e for e in events if e["type"] == "agent.assigned"}
    assert set(assigned) == {"U1", "U2", "U3", "U4"}
    worker_unit = {e["target"]: unit for unit, e in assigned.items()}
    assert len(worker_unit) == 4  # one worker per unit
    for unit in ("U1", "U2", "U3"):
        worker = assigned[unit]["target"]
        assert len([e for e in events if e["type"] == "agent.handoff" and e["actor"] == worker]) == 1
        assert len([e for e in events if e["type"] == "agent.retired" and e["target"] == worker]) == 1
    for before, after in (("U1", "U2"), ("U2", "U3"), ("U3", "U4")):  # FR-AGT-02: a unit waits for its dependencies
        worker = assigned[before]["target"]
        retired = next(e for e in events if e["type"] == "agent.retired" and e["target"] == worker)
        assert retired["seq"] < assigned[after]["seq"], (before, after)
    working = [e for e in events if e["type"] == "agent.working" and e["data"]["unit"] == "U4"]
    assert len(working) == 1 and working[0]["seq"] < requested["seq"]  # the sender is at work before it is gated
    loaded = {(worker_unit[e["actor"]], e["data"]["skill"]) for e in events if e["type"] == "skill.loaded"}
    assert loaded == {("U1", "web_research"), ("U2", "web_research"), ("U3", "exec_summary")}  # FR-AGT-03
    created = {e["data"]["artifact"]["artifact_id"]: e for e in events if e["type"] == "artifact.created"}
    assert set(created) == set(UNIT_ARTIFACT.values())
    assert all(e["data"]["artifact"]["version"] == 1 for e in created.values())
    assert created[UNIT_ARTIFACT["U4"]]["seq"] < requested["seq"]  # the draft exists before it is gated


def test_PRD_9_4_HR_1_the_world_only_moves_on_recorded_events(run_flow):
    """HR-1 at the API: nothing about the work is recorded before `world.started`, nothing is reported done while the
    gate is open, and every cause points at an earlier event of the same world."""
    run_flow.run_to_gate()
    stream = run_flow.quiet_stream()

    types = [e["type"] for e in run_flow.after_grant()]
    started = types.index("world.started")
    assert not [t for t in types[:started] if t.startswith(("agent.", "artifact.", "approval.", "skill.", "data."))]
    assert not {"artifact.delivered", "world.completed", "data.transfer"} & set(types)
    seen: set[str] = set()
    for event in stream:
        assert event["cause"] is None or event["cause"] in seen, (event["seq"], event["type"])
        seen.add(event["id"])
