"""WORLD-LIVE (FR-WLD-04, PRD 9.4/9.5): a live run records the events the world draws. Per building: planned (all of
them, first), constructing, operational, completed once every unit in it is done. Per worker: it walks from its Lead's
post to its building (agent.moved) before it works, and back to the Lead before it hands over (agent.moved, then
agent.handoff whose summary is the real note). Leads and the Director take a post first, so they are on the stage.
Nothing is emitted for a unit that did not run, and a failed unit completes no building. Only registered types."""

from __future__ import annotations

from typing import Any

from agt_support import (
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

NOTE = "Found three flights under the budget, the cheapest on Tuesday."


class NoteRunner:
    """A runner whose unit finishes with a note; `fail` names a unit that does not succeed."""

    def __init__(self, fail: frozenset[str] = frozenset()) -> None:
        self.fail = fail

    async def run(self, unit: dict[str, Any], context: Any) -> Any:
        from tilo_harness.executor import UnitOutcome

        return UnitOutcome(success=unit["id"] not in self.fail, summary=NOTE if unit["id"] not in self.fail else "no")


def _layout_two_buildings() -> dict[str, Any]:
    layout = build_layout(
        district_specs=[
            {
                "id": "D1",
                "lead": "A_lead",
                "specialists": ["A_s1", "A_s2"],
                "unit_ids": ["U1"],
                "building_name": "Find flights",
            }
        ]
    )
    district = layout["semantic"]["levels"][0]["districts"][0]
    district["buildings"].append(
        {"id": "B2", "name": "Book the hotel", "kind": "common", "common_type": "workshop", "plan_units": ["U2"]}
    )
    district["buildings"].append(
        {"id": "B3", "name": "Delivery Dock", "kind": "common", "common_type": "delivery_dock", "plan_units": []}
    )
    district["buildings"].append(
        {"id": "B4", "name": "Meeting Hall", "kind": "common", "common_type": "meeting_hall", "plan_units": []}
    )
    return layout


def _run(tmp_path, repo_root, fail: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    layout = _layout_two_buildings()
    plan = build_plan([build_unit("U1"), build_unit("U2", depends_on=["U1"])])
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id="w_world_live")
    run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=NoteRunner(fail))
    events = store.read_events("org_demo", "w_world_live")
    validator = EventValidator.from_repo(repo_root)
    assert {i: validator.problems(e) for i, e in enumerate(events) if validator.problems(e)} == {}
    return events


def _where(events, **match) -> list[int]:
    def hit(e):
        return all(e["data"].get(k, e.get(k)) == v for k, v in match.items())

    return [i for i, e in enumerate(events) if hit(e)]


def test_FR_WLD_04_WORLD_LIVE_every_building_is_planned_before_any_work_starts(tmp_path, repo_root):
    events = _run(tmp_path, repo_root)
    planned = [e for e in events if e["type"] == "building.planned"]
    assert [(e["target"], e["data"]["plan_units"], e["actor"]) for e in planned] == [
        ("B1", ["U1"], "A_dir"),
        ("B2", ["U2"], "A_dir"),
        ("B3", [], "A_dir"),  # the world's own buildings are planned too, so they are drawn and labelled
        ("B4", [], "A_dir"),
    ]
    first_work = next(i for i, e in enumerate(events) if e["type"] == "agent.assigned")
    assert all(events.index(e) < first_work for e in planned)
    assert all("Find flights" in planned[0]["summary"] or "Book the hotel" in planned[1]["summary"] for _ in [0])


def test_FR_WLD_04_WORLD_LIVE_a_building_goes_constructing_operational_then_completed(tmp_path, repo_root):
    events = _run(tmp_path, repo_root)
    for building, unit in (("B1", "U1"), ("B2", "U2")):
        steps = [e["type"] for e in events if e["target"] == building and e["type"].startswith("building.")]
        assert steps == ["building.planned", "building.constructing", "building.operational", "building.completed"]
        by_type = {e["type"]: e for e in events if e["target"] == building}
        assert by_type["building.constructing"]["data"] == {"unit": unit}
        assert by_type["building.operational"]["data"] == {"unit": unit}
        assert by_type["building.completed"]["data"] == {"unit_type": "research", "unit_count": 1}
    working = _where(events, type="agent.working", target="B1")[0]
    operational = _where(events, type="building.operational", target="B1")[0]
    handoff = _where(events, type="agent.handoff", actor="A_s1")[0]
    completed = _where(events, type="building.completed", target="B1")[0]
    assert operational < working < handoff < completed


def test_FR_WLD_04_WORLD_LIVE_leads_and_the_director_take_a_post_so_they_are_on_the_stage(tmp_path, repo_root):
    events = _run(tmp_path, repo_root)
    posts = {e["actor"]: e for e in events if e["type"] == "agent.moved" and e["actor"] in ("A_dir", "A_lead")}
    assert posts["A_lead"]["target"] == "B1" and posts["A_lead"]["data"] == {"from": "B1"}
    assert posts["A_dir"]["target"] == "B1"
    spawned = {e["target"]: i for i, e in enumerate(events) if e["type"] == "agent.spawned"}
    assert spawned["A_lead"] < events.index(posts["A_lead"]) and spawned["A_dir"] < events.index(posts["A_dir"])


def test_FR_WLD_04_WORLD_LIVE_a_worker_walks_to_its_building_then_back_to_its_lead_before_the_handoff(
    tmp_path, repo_root
):
    events = _run(tmp_path, repo_root)
    out = next(e for e in events if e["type"] == "agent.moved" and e["actor"] == "A_s2" and e["target"] == "B2")
    assert out["data"] == {"from": "B1"}  # from the Lead's post
    back = next(e for e in events if e["type"] == "agent.moved" and e["actor"] == "A_s2" and e["target"] == "B1")
    assert back["data"] == {"from": "B2"}
    order = [events.index(x) for x in (out,)] + _where(events, type="agent.working", actor="A_s2")
    order += [events.index(back)] + _where(events, type="agent.handoff", actor="A_s2")
    assert order == sorted(order) and len(order) == 4


def test_FR_WLD_04_WORLD_LIVE_no_walk_when_the_building_is_the_leads_own_post(tmp_path, repo_root):
    events = _run(tmp_path, repo_root)
    assert not [e for e in events if e["type"] == "agent.moved" and e["actor"] == "A_s1"]  # B1 is the Lead's post


def test_FR_WLD_04_WORLD_LIVE_the_handoff_carries_the_real_note_only_in_its_envelope(tmp_path, repo_root):
    # FR-AGT-08: the stage's speech bubble reads data.envelope.summary; the event's own line stays code-written.
    events = _run(tmp_path, repo_root)
    handoffs = [e for e in events if e["type"] == "agent.handoff"]
    assert len(handoffs) == 2 and all(e["data"]["envelope"]["summary"] == NOTE for e in handoffs)
    assert all(NOTE not in e["summary"] for e in handoffs)


def test_FR_WLD_04_WORLD_LIVE_assigned_says_which_unit_by_its_title(tmp_path, repo_root):
    events = _run(tmp_path, repo_root)
    assigned = [e["summary"] for e in events if e["type"] == "agent.assigned"]
    assert all("Unit U" in s for s in assigned)


def test_FR_WLD_04_WORLD_LIVE_a_failed_unit_completes_no_building(tmp_path, repo_root):
    events = _run(tmp_path, repo_root, fail=frozenset({"U1"}))
    assert [e["target"] for e in events if e["type"] == "building.completed"] == ["B4"]  # only the open hall
    assert [e["target"] for e in events if e["type"] == "building.operational"] == ["B1"]  # U2 never started
