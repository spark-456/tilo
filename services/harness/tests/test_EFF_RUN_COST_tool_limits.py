"""RUN-COST-PROGRESS (EFF-03/EFF-04, HR-1): a unit's tool loop is bounded by config/tool_loop.yaml.

Live evidence (16 Oct): one research unit spent 50.9 of 60 credits in seven minutes. The loop now has a round cap whose
last round is offered no tools, a total and a per-tool call cap, shorter results, a credit share, and every call that
really runs is reported once to the unit's progress hook. Fakes only; no network, no paid call.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from tilo_harness.executor import UnitContext
from tilo_harness.skills import LoadedSkill
from tilo_harness.tool_limits import ToolLimits, ToolLimitsError, load_tool_limits
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_harness.tools import FakeFetchUrl, FakeWebSearch, ToolRegistry, ToolResult
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.safety import FakeSafetyProvider

UNIT = {"id": "U1", "title": "Research pricing", "unit_type": "research", "role": "specialist"}
CONFIG = Path(__file__).resolve().parents[3] / "config" / "tool_loop.yaml"


class Greedy(FakeModelProvider):
    """Asks for `calls` web searches in every reply that offers tools, and answers once it is offered none."""

    def __init__(self, calls: int = 1, tool: str = "web_search") -> None:
        super().__init__("greedy")
        self.calls, self.tool, self.requests = calls, tool, []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        if not request.tools:
            return GenerateResponse(text="answer from what I have", profile_id="greedy")
        name = self.tool if self.tool in {t["function"]["name"] for t in request.tools} else "web_search"
        calls = [{"name": name, "args": {"query": f"q{len(self.requests)}-{n}"}} for n in range(self.calls)]
        return GenerateResponse(text=None, profile_id="greedy", tool_calls=calls)


class Long:
    name, description = "web_search", "Search."
    input_schema: Mapping[str, Any] = {"type": "object", "properties": {"query": {"type": "string"}}}
    tier, external_content, side_effect = "T1", True, False

    def __init__(self, size: int = 20_000, credits: float = 0.0) -> None:
        self.size, self.credits = size, credits

    def run(self, args: Mapping[str, Any]) -> ToolResult:
        return ToolResult("x" * self.size, self.credits)


def limits(**changes: Any) -> ToolLimits:
    return dataclasses.replace(load_tool_limits(), **changes)


def ctx(progress: Any = None, *tools: str) -> UnitContext:
    skill = LoadedSkill(
        id="s",
        version="1.0.0",
        body="Skill body.",
        sha256="0" * 64,
        tools_allowed=tuple(tools or ("web_search", "fetch_url")),
    )
    return UnitContext(agent_id="A_s0", skills=(skill,), progress=progress)


def run(provider: Greedy, tools: list[Any], lim: ToolLimits, context: UnitContext, **kwargs: Any) -> Any:
    runner = ToolUnitRunner(
        {"specialist": provider}, tools=ToolRegistry(tools), safety=FakeSafetyProvider(), limits=lim, **kwargs
    )
    return asyncio.run(runner.run_unit(UNIT, context))


def test_EFF_RUN_COST_config_loads_and_the_amounts_are_in_the_file() -> None:
    lim = load_tool_limits()
    assert lim.rounds <= 3 and lim.max_tool_calls <= 6 and lim.calls_per_tool["web_search"] <= 2
    assert lim.credit_share <= 0.5 and lim.result_chars < 6000 and lim.results_total_chars < 16000
    assert lim.line("web_search") != lim.line("fetch_url") != lim.line("anything_else")


def test_EFF_RUN_COST_a_bad_config_names_the_key_and_refuses(tmp_path: Path) -> None:
    bad = tmp_path / "t.yaml"
    bad.write_text(CONFIG.read_text(encoding="utf-8").replace("rounds: 3", "rounds: 0"), encoding="utf-8")
    with pytest.raises(ToolLimitsError, match="rounds"):
        load_tool_limits(bad)
    with pytest.raises(ToolLimitsError):
        load_tool_limits(tmp_path / "missing.yaml")


def test_EFF_RUN_COST_the_last_round_has_no_tools_and_the_unit_still_answers() -> None:
    provider = Greedy()
    result = run(provider, [FakeWebSearch(), FakeFetchUrl()], load_tool_limits(), ctx())
    lim = load_tool_limits()
    assert len(provider.requests) == lim.rounds
    assert all(r.tools for r in provider.requests[:-1]) and not provider.requests[-1].tools
    assert result.stop == "done" and result.outcome.success
    assert "No tools are available" in provider.requests[-1].prompt


def test_EFF_RUN_COST_parallel_function_calls_are_one_round() -> None:
    provider = Greedy(calls=4, tool="fetch_url")
    lim = limits(calls_per_tool={"web_search": 4, "fetch_url": 4}, max_tool_calls=6)
    result = run(provider, [FakeWebSearch(), FakeFetchUrl()], lim, ctx())
    assert len(provider.requests) <= lim.rounds
    assert {c.step for c in result.calls} <= {1, 2}
    assert len([c for c in result.calls if c.step == 1]) == 4


def test_EFF_RUN_COST_total_tool_calls_never_pass_the_cap() -> None:
    provider = Greedy(calls=4)
    lim = limits(rounds=5, calls_per_tool={"web_search": 50}, max_tool_calls=6)
    result = run(provider, [FakeWebSearch()], lim, ctx())
    ran = [c for c in result.calls if c.outcome != "refused"]
    assert len(ran) <= 6 and len(result.calls) <= 8
    assert result.outcome.success


def test_EFF_RUN_COST_a_tool_past_its_own_cap_is_not_run_and_not_offered_again() -> None:
    searched: list[str] = []

    class Counting(Long):
        def run(self, args: Mapping[str, Any]) -> ToolResult:
            searched.append(args["query"])
            return ToolResult("ok")

    provider = Greedy(calls=3)
    lim = limits(rounds=4, calls_per_tool={"web_search": 2}, max_tool_calls=6)
    result = run(provider, [Counting()], lim, ctx())
    assert len(searched) == 2
    assert result.outcome.success
    offered = [{t["function"]["name"] for t in (r.tools or [])} for r in provider.requests]
    assert offered[0] == {"web_search"} and offered[-1] == set()


def test_EFF_RUN_COST_results_are_cut_before_the_model_sees_them() -> None:
    provider = Greedy()
    lim = limits(result_chars=500, results_total_chars=900)
    run(provider, [Long()], lim, ctx())
    second = provider.requests[1].prompt
    assert "x" * 500 in second and "x" * 501 not in second


def test_EFF_RUN_COST_tools_stop_at_the_credit_share_and_the_unit_answers_from_what_it_has() -> None:
    provider = Greedy()
    lim = limits(rounds=6, max_tool_calls=6, calls_per_tool={"web_search": 6})
    result = run(provider, [Long(size=10, credits=10.0)], lim, ctx(), tool_credit_cap=15.0, credit_cap=100.0)
    assert result.stop == "done" and result.outcome.success
    assert len([c for c in result.calls if c.outcome == "ok"]) == 2  # 10 then 20 credits: past the 15 share
    assert not provider.requests[-1].tools


def test_EFF_RUN_COST_each_call_that_runs_reports_one_progress_line_and_a_cached_call_none() -> None:
    lines: list[str] = []
    provider = Greedy(calls=2)  # both ask q<step>-0 / q<step>-1: different queries, so no cache hit
    lim = limits(rounds=3)
    run(provider, [FakeWebSearch()], lim, ctx(lines.append))
    assert lines == [lim.line("web_search")] * len(lines) and 1 <= len(lines) <= 2 * (lim.rounds - 1)

    again: list[str] = []

    class Same(Greedy):
        def generate(self, request: GenerateRequest) -> GenerateResponse:
            self.requests.append(request)
            if not request.tools:
                return GenerateResponse(text="done", profile_id="greedy")
            return GenerateResponse(
                text=None, profile_id="g", tool_calls=[{"name": "web_search", "args": {"query": "a"}}]
            )

    result = run(Same(), [FakeWebSearch()], lim, ctx(again.append))
    assert [c.outcome for c in result.calls] == ["ok", "cached"] and len(again) == 1


def test_EFF_RUN_COST_a_failing_progress_hook_never_stops_the_unit() -> None:
    def boom(_line: str) -> None:
        raise RuntimeError("the writer refused")

    result = run(Greedy(), [FakeWebSearch()], load_tool_limits(), ctx(boom))
    assert result.outcome.success and result.calls


def test_HR_1_RUN_COST_a_unit_progress_line_becomes_a_registered_agent_working_event(tmp_path, repo_root) -> None:
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

    class Searching:
        async def run(self, unit: Mapping[str, Any], context: UnitContext) -> Any:
            from tilo_harness.executor import UnitOutcome

            assert context.progress is not None
            context.progress("The agent is searching the web.")
            context.progress("The agent is reading a web page.")
            return UnitOutcome(success=True, summary="done")

    layout = build_layout(district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": ["U1"]}])
    plan = build_plan([build_unit("U1", skills=["web_research"])])
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id="w_progress")
    run_plan_sync(plan, layout, writer=writer, config=config, skills=skills, runner=Searching())
    events = store.read_events("org_demo", "w_progress")

    working = [e for e in events if e["type"] == "agent.working" and e["actor"] == "A_s0"]
    assert [e["summary"] for e in working][-2:] == [
        "The agent is searching the web.",
        "The agent is reading a web page.",
    ]
    assert all(e["data"] == {"unit": "U1"} for e in working)
    validator = EventValidator.from_repo(repo_root)
    assert [validator.problems(e) for e in events if validator.problems(e)] == []
    handoff = next(i for i, e in enumerate(events) if e["type"] == "agent.handoff")
    assert all(events.index(e) < handoff for e in working)
