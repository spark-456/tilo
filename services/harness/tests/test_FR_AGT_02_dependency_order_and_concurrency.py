"""FR-AGT-02 (PRD 8.6): "Specialists run units in parallel where the plan graph allows." Ticket
brief acceptance: "a plan of 4 independent research units runs all 4 at once (max_specialists >=
4); a chain A -> B -> C runs strictly in order; a diamond runs its two middle units together."
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


def _config(tmp_path, max_specialists: int = 6):
    return load_config_sync(write_agents_config(tmp_path / "agents.yaml", limits={"max_specialists": max_specialists}))


def _skills(tmp_path):
    return make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))


def test_FR_AGT_02_four_independent_units_run_concurrently(tmp_path) -> None:
    unit_ids = ["U1", "U2", "U3", "U4"]
    specialists = ["A_s1", "A_s2", "A_s3", "A_s4"]
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": specialists, "unit_ids": unit_ids}]
    )
    plan = build_plan([build_unit(uid) for uid in unit_ids])
    writer, _store = make_memory_writer(layout, world_id="w_four_parallel")
    runner = RecordingRunner(release_immediately=True)

    result = run_plan_sync(
        plan, layout, writer=writer, config=_config(tmp_path, 4), skills=_skills(tmp_path), runner=runner
    )

    assert result is not None
    assert sorted(runner.starts) == unit_ids
    assert runner.max_in_flight == 4, (
        f"FR-AGT-02: with max_specialists >= 4 all 4 independent units must run at once, "
        f"got max concurrency {runner.max_in_flight}"
    )


def test_FR_AGT_02_chain_runs_strictly_in_order(tmp_path) -> None:
    layout = build_layout(
        district_specs=[
            {"id": "D1", "lead": "A_lead", "specialists": ["A_s1", "A_s2", "A_s3"], "unit_ids": ["A", "B", "C"]}
        ]
    )
    plan = build_plan(
        [
            build_unit("A"),
            build_unit("B", depends_on=["A"]),
            build_unit("C", depends_on=["B"]),
        ]
    )
    writer, _store = make_memory_writer(layout, world_id="w_chain")
    runner = RecordingRunner(release_immediately=True)

    run_plan_sync(plan, layout, writer=writer, config=_config(tmp_path), skills=_skills(tmp_path), runner=runner)

    assert runner.starts == ["A", "B", "C"], f"FR-AGT-02: a chain must run strictly in order, got {runner.starts}"
    assert runner.max_in_flight == 1, (
        f"FR-AGT-02: a chain must never overlap, got max concurrency {runner.max_in_flight}"
    )
    # A must fully finish (be in `ends`) before B ever starts.
    assert runner.ends.index("A") < runner.starts.index("B")
    assert runner.ends.index("B") < runner.starts.index("C")


def test_FR_AGT_02_diamond_runs_middle_two_concurrently(tmp_path) -> None:
    """A -> {B, C} -> D: B and C are independent of each other and must run together; D must
    wait for both."""
    layout = build_layout(
        district_specs=[
            {
                "id": "D1",
                "lead": "A_lead",
                "specialists": ["A_s1", "A_s2", "A_s3", "A_s4"],
                "unit_ids": ["A", "B", "C", "D"],
            }
        ]
    )
    plan = build_plan(
        [
            build_unit("A"),
            build_unit("B", depends_on=["A"]),
            build_unit("C", depends_on=["A"]),
            build_unit("D", depends_on=["B", "C"]),
        ]
    )
    writer, _store = make_memory_writer(layout, world_id="w_diamond")
    runner = RecordingRunner(release_immediately=True)

    run_plan_sync(plan, layout, writer=writer, config=_config(tmp_path, 4), skills=_skills(tmp_path), runner=runner)

    assert runner.ends.index("A") < runner.starts.index("B")
    assert runner.ends.index("A") < runner.starts.index("C")
    assert runner.max_in_flight >= 2, "FR-AGT-02: the diamond's two middle units (B, C) must run together"
    assert runner.ends.index("B") < runner.starts.index("D")
    assert runner.ends.index("C") < runner.starts.index("D")
    assert runner.starts[-1] == "D" and runner.starts.index("D") == 3
