"""FR-AGT-01 acceptance test (PRD 8.6): "Changing max_specialists to 3 caps concurrency at 3 in a
load test." A config file with max_specialists=3 is written by this test (never the real,
S0-owned config/agents.yaml); 10 independent Specialist units (no depends_on among them, so
nothing but the cap serializes them) must never run more than 3 at once, and must actually reach
3 -- a lower true concurrency would also "never exceed 3" and pass a weaker test for the wrong
reason.

Uses `agt_support.RecordingRunner(release_immediately=False)`: each unit's `run()` blocks on a
shared `asyncio.Event` so the test can hold several units open at once and poll `in_flight`
deterministically (asyncio coordination, never a wall-clock sleep, per the ticket brief).
"""

from __future__ import annotations

import asyncio

from agt_support import (
    RecordingRunner,
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    wait_until,
    write_agents_config,
)
from conftest import make_memory_writer

N_UNITS = 10
CAP = 3


def _layout_and_plan() -> tuple[dict, dict]:
    specialists = [f"A_s{i}" for i in range(N_UNITS)]
    unit_ids = [f"U{i}" for i in range(N_UNITS)]
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": specialists, "unit_ids": unit_ids}]
    )
    plan = build_plan([build_unit(uid) for uid in unit_ids])
    return layout, plan


def test_FR_AGT_01_ten_independent_units_never_exceed_and_do_reach_the_max_specialists_cap_of_3(tmp_path) -> None:
    from tilo_harness.executor import run_plan

    config_path = write_agents_config(tmp_path / "agents.yaml", limits={"max_specialists": CAP})
    config = load_config_sync(config_path)
    layout, plan = _layout_and_plan()
    writer, store = make_memory_writer(layout, world_id="w_cap_test")
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    runner = RecordingRunner(release_immediately=False)

    async def scenario() -> None:
        task = asyncio.create_task(run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=runner))
        await wait_until(lambda: runner.in_flight >= CAP)
        assert runner.in_flight == CAP, f"must reach the cap of {CAP}, got {runner.in_flight}"
        # Hold here for a while: with 10 independent units and only the cap serializing them, a
        # 4th must not be able to start while these 3 are still open.
        for _ in range(200):
            await asyncio.sleep(0)
            assert runner.in_flight <= CAP, f"FR-AGT-01: concurrency exceeded the cap of {CAP}: {runner.in_flight}"
        runner.release_all()
        await task

    asyncio.run(scenario())

    assert sorted(runner.starts) == sorted(f"U{i}" for i in range(N_UNITS)), "all 10 units must eventually run"
    assert runner.max_in_flight == CAP, f"FR-AGT-01: cap must be reached exactly, got max {runner.max_in_flight}"
