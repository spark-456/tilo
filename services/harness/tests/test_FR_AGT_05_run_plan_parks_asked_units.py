"""FR-AGT-05 through the executor's public entry point, `run_plan(..., must_ask=...)`.

Given a plan with one unit that plants an ambiguity and one clear unit, When the plan runs with the
must-ask rules on, Then the ambiguous unit asks before any work (the runner never starts it) with
the Specialist -> Lead -> Director -> person chain in the Trace, the clear unit runs normally with
no question events, and the run returns instead of hanging (the unit is parked until a person
answers; answering is FR-AGT-06/07, BQ-201). Without `must_ask` nothing changes.
"""

from __future__ import annotations

import asyncio

from agt_must_ask_support import DIRECTOR, LEAD, OWNER, WORLD, load_tasks, make_must_ask, specialist_script
from agt_support import (
    RecordingRunner,
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from tilo_harness.executor import run_plan

ASK_TASK = next(task for task in load_tasks() if task["id"] == "ASK-06")  # "Compare the two vendor quotes"
CLEAR_TASK = next(task for task in load_tasks() if task["id"] == "CLR-01")
QUESTION_TYPES = {"agent.help_requested", "agent.escalated", "question.routed"}


def _run(tmp_path, *, with_must_ask: bool):
    layout = build_layout(
        world_id=WORLD,
        director_id=DIRECTOR,
        district_specs=[{"id": "D1", "lead": LEAD, "specialists": ["A_s0", "A_s1"], "unit_ids": ["U1", "U2"]}],
    )
    plan = build_plan(
        [build_unit("U1", title=ASK_TASK["title"]), build_unit("U2", title=CLEAR_TASK["title"])],
    )
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id=WORLD)
    runner = RecordingRunner(release_immediately=True)
    specialist = specialist_script([ASK_TASK, CLEAR_TASK])
    must_ask, cards, _providers = make_must_ask(tmp_path, specialist)

    kwargs = {"must_ask": must_ask} if with_must_ask else {}

    async def go():
        return await asyncio.wait_for(
            run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=runner, **kwargs), timeout=20
        )

    asyncio.run(go())
    return store.read_events("org_demo", WORLD), runner, cards, specialist


def test_FR_AGT_05_run_plan_asks_before_working_on_the_ambiguous_unit_and_runs_the_clear_one(tmp_path) -> None:
    events, runner, cards, specialist = _run(tmp_path, with_must_ask=True)

    assert specialist.misses == []
    assert runner.starts == ["U2"], "the ambiguous unit must not start its work until a person answers"
    assert len(cards) == 1

    by_type = {t: [e for e in events if e["type"] == t] for t in QUESTION_TYPES}
    assert {t: len(v) for t, v in by_type.items()} == {t: 1 for t in QUESTION_TYPES}, "one chain, for U1 only"

    assigned_u1 = next(e for e in events if e["type"] == "agent.assigned" and e["data"]["unit"] == "U1")
    worker = assigned_u1["target"]
    helped, escalated, routed = (by_type[t][0] for t in ("agent.help_requested", "agent.escalated", "question.routed"))
    assert assigned_u1["seq"] < helped["seq"] < escalated["seq"] < routed["seq"]
    assert (helped["actor"], helped["target"], helped["data"]["unit"]) == (worker, LEAD, "U1")
    assert (escalated["actor"], escalated["target"], escalated["data"]["reason"]) == (LEAD, DIRECTOR, "ambiguous_brief")
    assert (routed["actor"], routed["target"], routed["data"]["card_id"]) == (LEAD, OWNER, cards[0]["id"])


def test_FR_AGT_05_run_plan_raises_no_question_for_the_clear_unit_and_it_still_hands_off(tmp_path) -> None:
    events, _runner, _cards, _specialist = _run(tmp_path, with_must_ask=True)

    assigned_u2 = next(e for e in events if e["type"] == "agent.assigned" and e["data"]["unit"] == "U2")
    worker = assigned_u2["target"]
    assert [e for e in events if e["type"] in QUESTION_TYPES and worker in (e["actor"], e["target"])] == []
    assert any(e["type"] == "agent.handoff" and e["data"]["envelope"]["from"] == worker for e in events)


def test_FR_AGT_05_without_must_ask_run_plan_behaves_as_before(tmp_path) -> None:
    events, runner, cards, _specialist = _run(tmp_path, with_must_ask=False)
    assert sorted(runner.starts) == ["U1", "U2"]
    assert cards == [] and [e for e in events if e["type"] in QUESTION_TYPES] == []
