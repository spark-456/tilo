"""FR-AGT-02 ticket brief item 4: every event `run_plan` writes is registered and valid, `seq`
stays dense from 1 (single `WorldWriter`, PRD 9.3), and for a Specialist unit the event types
appear in this order: agent.spawned -> agent.assigned -> skill.loaded (per skill) ->
agent.working -> agent.handoff (typed envelope, Specialist to Lead) -> agent.retired.
"""

from __future__ import annotations

from agt_support import (
    RecordingRunner,
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    run_plan_sync,
    write_agents_config,
)
from conftest import make_memory_writer
from tilo_harness.validator import EventValidator

SPECIALIST_ID = "A_s0"


def _run_single_skilled_unit(tmp_path):
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": [SPECIALIST_ID], "unit_ids": ["U1"]}]
    )
    plan = build_plan([build_unit("U1", skills=["web_research"])])
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id="w_events_order")
    runner = RecordingRunner(release_immediately=True)

    run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=runner)
    return store.read_events("org_demo", "w_events_order"), layout


def test_FR_AGT_02_every_written_event_validates_with_dense_seq_from_1(tmp_path, repo_root) -> None:
    events, _layout = _run_single_skilled_unit(tmp_path)
    assert events, "run_plan must write at least one event"

    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(events) + 1)), f"seq must be dense and strictly increasing from 1, got {seqs}"

    validator = EventValidator.from_repo(repo_root)
    offenders = {i: validator.problems(e) for i, e in enumerate(events) if validator.problems(e)}
    assert offenders == {}, f"run_plan wrote event(s) that fail the contract: {offenders}"


def test_FR_AGT_02_event_types_appear_in_order_for_a_specialist_unit(tmp_path, repo_root) -> None:
    events, _layout = _run_single_skilled_unit(tmp_path)

    def first_index(predicate) -> int:
        for i, e in enumerate(events):
            if predicate(e):
                return i
        raise AssertionError(f"no matching event found among types {[e['type'] for e in events]}")

    spawned_ix = first_index(
        lambda e: e["type"] == "agent.spawned" and e["target"] == SPECIALIST_ID and e["data"]["role"] == "specialist"
    )
    assigned_ix = first_index(
        lambda e: e["type"] == "agent.assigned" and e["target"] == SPECIALIST_ID and e["data"]["unit"] == "U1"
    )
    skill_ix = first_index(
        lambda e: e["type"] == "skill.loaded" and e["actor"] == SPECIALIST_ID and e["data"]["skill"] == "web_research"
    )
    working_ix = first_index(lambda e: e["type"] == "agent.working" and e["actor"] == SPECIALIST_ID)
    handoff_ix = first_index(lambda e: e["type"] == "agent.handoff" and e["data"]["envelope"]["from"] == SPECIALIST_ID)
    retired_ix = first_index(lambda e: e["type"] == "agent.retired" and e["target"] == SPECIALIST_ID)

    assert spawned_ix < assigned_ix < skill_ix < working_ix < handoff_ix < retired_ix, (
        "FR-AGT-02: event types must appear in order agent.spawned -> agent.assigned -> "
        f"skill.loaded -> agent.working -> agent.handoff -> agent.retired, got order "
        f"{[e['type'] for e in events]}"
    )

    handoff_envelope = events[handoff_ix]["data"]["envelope"]
    for field in ("from", "to", "artifact_refs", "summary", "acceptance_criteria", "provenance_ids"):
        assert field in handoff_envelope, f"agent.handoff envelope missing {field!r} (envelope.schema.json)"
    assert handoff_envelope["to"] == "A_lead", "the Specialist must hand its result back to its Lead"
