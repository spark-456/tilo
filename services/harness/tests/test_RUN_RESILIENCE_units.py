"""A transient provider outage pauses only its unit and retries before failing the run."""

from __future__ import annotations

import asyncio

from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_providers.router import RouterAttempt, RouterExhaustedError


class _Overloaded:
    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    async def run(self, unit, context):
        self.calls += 1
        if self.calls <= self.failures:
            raise RouterExhaustedError(
                "overloaded",
                [
                    RouterAttempt("flash-a", "fake", "error", error_type="QuotaError"),
                    RouterAttempt("flash-b", "fake", "error", error_type="RetryableError"),
                ],
            )
        return UnitOutcome(success=True, summary="done")


def _run(tmp_path, monkeypatch, failures):
    waits = []

    async def wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr("tilo_harness.executor._transient_wait", wait)
    layout = build_layout(district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0"], "unit_ids": ["U1"]}])
    plan = build_plan([build_unit("U1")])
    writer, store = make_memory_writer(layout, world_id="w_resilience")
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    runner = _Overloaded(failures)
    result = asyncio.run(run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=runner))
    return result, runner, waits, store


def test_RUN_RESILIENCE_transient_exhaustion_retries_same_unit_and_completes(tmp_path, monkeypatch):
    result, runner, waits, store = _run(tmp_path, monkeypatch, 2)
    assert result.outcomes["U1"].success
    assert runner.calls == 3
    assert waits == [60, 120]
    assert [e["type"] for e in store.read_events("org_demo", "w_resilience")].count("agent.working") >= 2


def test_RUN_RESILIENCE_three_transient_failures_stop_the_unit(tmp_path, monkeypatch):
    result, runner, waits, _store = _run(tmp_path, monkeypatch, 3)
    assert result.failed == ["U1"]
    assert runner.calls == 3
    assert waits == [60, 120]
