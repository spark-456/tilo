"""FR-AGT-03 (run half): in a real run, a research unit the Director gave no skill still gets web_search and fetch_url.

Same rig as RUN-FAIL-1 (production runner, real router, real Google adapter, faked network client); the only change is
that the compiled plan's research unit pins no skill. Both tools stay T1 and read-only, and the writer gets none.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig

pytestmark = pytest.mark.usefixtures("must_ask_ask_mode")


def test_FR_AGT_03_a_research_unit_with_no_skill_gets_the_web_tools(tmp_path, monkeypatch):
    run, state, _asking, models = rig._run(tmp_path, monkeypatch, cap=40)
    compile_plan = run.seams.compiler

    def without_skills(**kwargs):
        plan = compile_plan(**kwargs)
        for unit in plan["units"]:
            unit["skills"] = []
        return plan

    run.seams = dataclasses.replace(run.seams, compiler=without_skills)

    asyncio.run(rig._answer_and_finish(run, state))

    assert [e for e in state.events[rig.WORLD] if e["type"] == "world.failed"] == []
    with_tools = [c for c in models.configs if getattr(c, "tools", None)]
    assert with_tools, "the research unit's model call carried no tools"
    names = {d.name for config in with_tools for d in config.tools[0].function_declarations}
    assert names == {"web_search", "fetch_url"}
    assert len(with_tools) < len(models.configs), "the writer's calls stay tool-free"
