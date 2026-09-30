"""FR-AGT-02 / plan.rules.md PG-02, PG-03: `run_plan` "first checks PG-02 and PG-03 and refuses a
plan with an unknown dependency or a cycle, writing nothing" (ticket brief item 2). Both checks
must run *before* any event is written -- the store must stay completely empty, not just "not
fully written".

Builds the malformed plans by hand rather than through `agt_support.build_plan` (which
self-validates a plan against plan.schema.json -- these plans ARE schema-valid; PG-02/PG-03 are
cross-reference rules the schema cannot express, per contracts/plan.rules.md's own "Schema"
column).
"""

from __future__ import annotations

from agt_support import (
    build_approaches,
    build_layout,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    run_plan_sync,
    write_agents_config,
)
from conftest import make_memory_writer


def _layout() -> dict:
    return build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0", "A_s1"], "unit_ids": ["U1", "U2"]}]
    )


def _config(tmp_path) -> object:
    return load_config_sync(write_agents_config(tmp_path / "agents.yaml"))


def _plan(units: list[dict]) -> dict:
    return {"approaches": build_approaches(), "chosen_approach": "quick", "units": units, "gates": [], "budget_cap": 10}


def _assert_refused_and_nothing_written(plan: dict, world_id: str, rule: str, tmp_path) -> None:
    layout = _layout()
    config = _config(tmp_path)
    writer, store = make_memory_writer(layout, world_id=world_id)
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))

    raised = False
    try:
        run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=object())
    except Exception:  # noqa: BLE001 -- the executor's own exception type; only "it refused" matters here
        raised = True
    assert raised, f"{rule}: a bad plan must be refused before running"
    assert store.read_events("org_demo", world_id) == [], f"{rule}: a refused plan must write nothing at all"


def test_FR_AGT_02_unknown_dependency_pg02_refused_writes_nothing(tmp_path) -> None:
    plan = _plan([build_unit("U1", depends_on=["U_does_not_exist"])])
    _assert_refused_and_nothing_written(plan, "w_pg02_unknown", "PG-02", tmp_path)


def test_FR_AGT_02_self_dependency_pg02_refused_writes_nothing(tmp_path) -> None:
    """PG-02 also covers "no unit depends on itself"."""
    plan = _plan([build_unit("U1", depends_on=["U1"])])
    _assert_refused_and_nothing_written(plan, "w_pg02_self", "PG-02", tmp_path)


def test_FR_AGT_02_cycle_pg03_refused_writes_nothing(tmp_path) -> None:
    plan = _plan([build_unit("U1", depends_on=["U2"]), build_unit("U2", depends_on=["U1"])])
    _assert_refused_and_nothing_written(plan, "w_pg03", "PG-03", tmp_path)
