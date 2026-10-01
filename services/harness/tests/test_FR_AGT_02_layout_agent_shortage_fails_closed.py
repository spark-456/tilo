"""FR-AGT-01/02 ticket brief: "the executor gets its agent ids from the layout's agents (and
fails closed if the layout has too few agents of a rank for the plan)." Each scenario here is
schema-valid (layout.schema.json does not know about the plan) but leaves the executor with too
few agents of some rank to run the plan; it must refuse before writing anything, never crash with
an unrelated KeyError/IndexError partway through a run.
"""

from __future__ import annotations

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


def _config(tmp_path):
    return load_config_sync(write_agents_config(tmp_path / "agents.yaml"))


def _skills(tmp_path):
    return make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))


def _assert_fails_closed(layout: dict, plan: dict, world_id: str, tmp_path, reason: str) -> None:
    writer, store = make_memory_writer(layout, world_id=world_id)
    raised = False
    try:
        run_plan_sync(plan, layout, writer=writer, config=_config(tmp_path), skills=_skills(tmp_path), runner=object())
    except Exception:  # noqa: BLE001 -- the executor's own exception type; only "it refused" matters here
        raised = True
    assert raised, f"{reason}: the executor must fail closed, not run with too few agents"
    assert store.read_events("org_demo", world_id) == [], f"{reason}: nothing may be written once refused"


def test_FR_AGT_02_no_specialist_rank_agent_for_a_specialist_unit_fails_closed(tmp_path) -> None:
    layout = build_layout(district_specs=[{"id": "D1", "lead": "A_lead", "specialists": [], "unit_ids": ["U1"]}])
    plan = build_plan([build_unit("U1", role="specialist")])
    _assert_fails_closed(layout, plan, "w_shortage_no_specialist", tmp_path, "layout has zero specialist-rank agents")


def test_FR_AGT_02_no_director_rank_agent_in_the_layout_fails_closed(tmp_path) -> None:
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": ["U1"]}],
        director_id=None,
    )
    plan = build_plan([build_unit("U1")])
    _assert_fails_closed(layout, plan, "w_shortage_no_director", tmp_path, "layout has zero director-rank agents")


def test_FR_AGT_02_district_lead_id_has_no_lead_rank_agent_fails_closed(tmp_path) -> None:
    """The district's `lead` field must name an agent whose `rank` is actually "lead" (PRD 8.1:
    one Lead per district); a district whose named lead is really a specialist-rank agent is a
    layout with "too few" lead-rank agents for its districts."""
    layout = build_layout(
        district_specs=[
            {
                "id": "D1",
                "lead": "A_s0",
                "skip_auto_lead_agent": True,
                "specialists": ["A_s0"],
                "unit_ids": ["U1"],
            }
        ]
    )
    plan = build_plan([build_unit("U1")])
    _assert_fails_closed(layout, plan, "w_shortage_bad_lead_rank", tmp_path, "district lead id is not lead-rank")
