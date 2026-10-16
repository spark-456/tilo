"""RUN-COST-PROGRESS (EFF-03, HR-1), run half. Same production rig as RUN-FAIL-1 (real runner, real router, real Google
adapter, faked network client). The research unit's model asks for four parallel searches in every reply that offers
tools, which is how a live unit spent 50.9 of 60 credits. Now: at most `rounds` model calls, the last without tools, at
most `calls_per_tool` searches, the SDK's own function-calling loop off, and each search that really ran is one
agent.working event the world can show.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
import test_RUN_FAIL_1_tool_unit_after_answer as rig
from tilo_harness.tool_limits import load_tool_limits

pytestmark = pytest.mark.usefixtures("must_ask_ask_mode")


class Greedy(rig.FakeModels):
    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        reply = super().generate_content(model=model, contents=contents, config=config)
        if getattr(config, "tools", None):
            queries = (f"pricing {len(self.configs)} {n}" for n in range(4))
            calls = [SimpleNamespace(name="web_search", args={"query": q}) for q in queries]
            reply.function_calls, reply.text = calls, None
        return reply


def _finish(tmp_path, monkeypatch):
    monkeypatch.setattr(rig, "FakeModels", Greedy)
    run, state, _asking, models = rig._run(tmp_path, monkeypatch, cap=60)
    asyncio.run(rig._answer_and_finish(run, state))
    return state, models


def test_EFF_RUN_COST_a_greedy_research_unit_is_bounded_and_still_delivers(tmp_path, monkeypatch) -> None:
    state, models = _finish(tmp_path, monkeypatch)
    limits = load_tool_limits()
    events = state.events[rig.WORLD]

    assert [e for e in events if e["type"] == "world.failed"] == []
    assert any(e["type"] == "world.completed" for e in events)
    with_tools = [c for c in models.configs if getattr(c, "tools", None)]
    assert 1 <= len(with_tools) <= limits.rounds - 1, "the last round of the unit is offered no tools"
    assert all(c.automatic_function_calling.disable is True for c in models.configs), "the SDK must not loop itself"


def test_EFF_RUN_COST_every_search_that_ran_is_one_agent_working_event(tmp_path, monkeypatch) -> None:
    state, _models = _finish(tmp_path, monkeypatch)
    limits = load_tool_limits()
    events = state.events[rig.WORLD]

    said = [e for e in events if e["type"] == "agent.working" and e["summary"] == limits.line("web_search")]
    assert 1 <= len(said) <= limits.calls_per_tool["web_search"]
    assert all(e["data"] == {"unit": "U1"} and e["actor"].startswith("A_") for e in said)
    first, last = events.index(said[0]), events.index(said[-1])
    handoff = next(i for i, e in enumerate(events) if e["type"] == "agent.handoff" and e["actor"] == said[0]["actor"])
    assert first <= last < handoff
