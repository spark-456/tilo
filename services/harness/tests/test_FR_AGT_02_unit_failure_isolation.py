"""FR-AGT-02 / FR-AGT-03 / FR-AGT-01: a unit's failure of any kind fails that unit only.

Its dependents are skipped, it still retires (HR-2: no agent is left "working"), and every
other unit hands off and retires. Only a cancel of `run_plan` itself ends the run.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
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
from tilo_harness.config import AgentsConfigError, load_agents_config
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_harness.validator import EventValidator

ULID = "01J00000000000000000000000"
BAD_OUTCOMES = {
    "bad_artifact_ref": UnitOutcome(success=True, artifact_refs=({"bogus": 1},)),
    "duplicate_provenance": UnitOutcome(success=True, provenance_ids=(ULID, ULID)),
    "non_ulid_provenance": UnitOutcome(success=True, provenance_ids=("not-a-ulid",)),
    "non_str_summary": UnitOutcome(success=True, summary=42),  # type: ignore[arg-type]
    "refs_not_a_sequence": UnitOutcome(success=True, artifact_refs=7),  # type: ignore[arg-type]
    "success_not_bool": UnitOutcome(success="yes"),  # type: ignore[arg-type]
    # Envelope-schema valid, but the writer's EventValidator rejects the handoff event.
    "too_many_artifact_refs": UnitOutcome(
        success=True, artifact_refs=tuple({"artifact_id": f"art_{i}", "version": 1} for i in range(40_000))
    ),
    "lone_surrogate_summary": UnitOutcome(success=True, summary="a\ud800b"),
}


def _setup(tmp_path: Path, world: str, *, n: int = 3, deps: dict[str, list[str]] | None = None) -> Any:
    ids = [f"U{i}" for i in range(1, n + 1)]
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": [f"A_s{i}" for i in range(n)], "unit_ids": ids}]
    )
    plan = build_plan([build_unit(u, depends_on=(deps or {}).get(u)) for u in ids])
    writer, store = make_memory_writer(layout, world_id=world)
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    return plan, layout, writer, store, config, skills


def _events(store: Any, world: str) -> list[dict[str, Any]]:
    events = store.read_events("org_demo", world)
    validator = EventValidator.from_repo()
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert all(not validator.problems(e) for e in events)
    working = {e["actor"] for e in events if e["type"] == "agent.working"}
    retired = {e["target"] for e in events if e["type"] == "agent.retired"}
    assert working <= retired, f"agents left working (HR-2): {sorted(working - retired)}"
    return events


class _Runner:
    def __init__(self, bad: Any) -> None:
        self.bad = bad

    async def run(self, unit: dict[str, Any], context: Any) -> UnitOutcome:
        await asyncio.sleep(0)
        if unit["id"] == "U1":
            return await self.bad() if callable(self.bad) else self.bad
        await asyncio.sleep(0.01)  # siblings still running when U1 ends
        return UnitOutcome(success=True, summary="ok")


@pytest.mark.parametrize("name", sorted(BAD_OUTCOMES))
def test_FR_AGT_02_invalid_runner_outcome_fails_only_that_unit(tmp_path: Path, name: str) -> None:
    plan, layout, writer, store, config, skills = _setup(tmp_path, "w_bad")

    result = asyncio.run(
        run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=_Runner(BAD_OUTCOMES[name]))
    )

    assert result.failed == ["U1"]
    assert result.outcomes["U1"].success is False
    events = _events(store, "w_bad")
    handoffs = {e["actor"] for e in events if e["type"] == "agent.handoff"}
    assert handoffs == {"A_s1", "A_s2"}, "only the valid units hand off"
    assert {e["target"] for e in events if e["type"] == "agent.retired"} >= {"A_s0", "A_s1", "A_s2"}


def test_FR_AGT_02_runner_self_cancel_fails_unit_and_skips_dependents(tmp_path: Path) -> None:
    plan, layout, writer, store, config, skills = _setup(tmp_path, "w_cancel", deps={"U2": ["U1"]})

    async def self_cancel() -> UnitOutcome:
        inner = asyncio.create_task(asyncio.sleep(10))
        await asyncio.sleep(0)
        inner.cancel()
        await inner  # CancelledError the outer run never asked for
        return UnitOutcome(success=True)

    async def go() -> Any:
        run = run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=_Runner(self_cancel))
        return await asyncio.wait_for(run, timeout=5)

    result = asyncio.run(go())

    assert result.failed == ["U1"]
    assert result.skipped == ["U2"]
    assert result.outcomes["U3"].success is True
    events = _events(store, "w_cancel")
    assert "A_s0" in {e["target"] for e in events if e["type"] == "agent.retired"}


def test_FR_AGT_02_runner_cancelling_current_task_fails_unit_and_skips_dependents(tmp_path: Path) -> None:
    plan, layout, writer, store, config, skills = _setup(tmp_path, "w_cancel_self", deps={"U2": ["U1"]})

    async def cancel_current_task() -> UnitOutcome:
        task = asyncio.current_task()
        assert task is not None
        task.cancel()
        await asyncio.sleep(0)
        return UnitOutcome(success=True)

    async def go() -> Any:
        run = run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=_Runner(cancel_current_task))
        return await asyncio.wait_for(run, timeout=5)

    result = asyncio.run(go())

    assert result.failed == ["U1"]
    assert result.skipped == ["U2"]
    assert result.outcomes["U3"].success is True
    events = _events(store, "w_cancel_self")
    assert "A_s0" in {e["target"] for e in events if e["type"] == "agent.retired"}


def test_FR_AGT_02_outer_cancel_of_run_plan_still_propagates(tmp_path: Path) -> None:
    plan, layout, writer, _store, config, skills = _setup(tmp_path, "w_outer")

    class Hang:
        async def run(self, unit: dict[str, Any], context: Any) -> UnitOutcome:
            await asyncio.Event().wait()
            return UnitOutcome(success=True)

    async def go() -> None:
        task = asyncio.create_task(run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=Hang()))
        await asyncio.sleep(0.05)
        task.cancel()
        await task

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())


HOSTILE_YAML = {
    "huge_int": lambda raw: raw + b"\nx: " + b"9" * 5000 + b"\n",
    "deep_nesting": lambda raw: b"[" * 5000 + b"]" * 5000,
}


@pytest.mark.parametrize("kind", sorted(HOSTILE_YAML))
def test_FR_AGT_03_skill_turned_hostile_mid_run_fails_only_its_unit(tmp_path: Path, kind: str) -> None:
    layout = build_layout(
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_s0", "A_s1"], "unit_ids": ["U1", "U2"]}]
    )
    plan = build_plan([build_unit("U1"), build_unit("U2", depends_on=["U1"], skills=["web_research"])])
    writer, store = make_memory_writer(layout, world_id="w_sk")
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    root = copy_skills_fixture_tree(tmp_path / "skills")
    skills = make_skill_registry(root)
    skill_yaml = root / "research/web_research/skill.yaml"

    class Mutate:
        async def run(self, unit: dict[str, Any], context: Any) -> UnitOutcome:
            if unit["id"] == "U1":
                skill_yaml.write_bytes(HOSTILE_YAML[kind](skill_yaml.read_bytes()))
            return UnitOutcome(success=True)

    result = asyncio.run(run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=Mutate()))

    assert result.outcomes["U1"].success is True
    assert result.failed == ["U2"]
    _events(store, "w_sk")


@pytest.mark.parametrize("kind", sorted(HOSTILE_YAML))
def test_FR_AGT_03_registry_lists_hostile_skill_yaml_as_problem(tmp_path: Path, kind: str) -> None:
    root = copy_skills_fixture_tree(tmp_path / "skills")
    skill_yaml = root / "research/web_research/skill.yaml"
    skill_yaml.write_bytes(HOSTILE_YAML[kind](skill_yaml.read_bytes()))

    registry = make_skill_registry(root)

    assert "research/web_research" in registry.problems
    assert "web_research" not in dict(registry.catalog())


@pytest.mark.parametrize("kind", sorted(HOSTILE_YAML))
def test_FR_AGT_01_hostile_agents_yaml_is_agents_config_error(tmp_path: Path, kind: str) -> None:
    path = write_agents_config(tmp_path / "agents.yaml")
    path.write_bytes(HOSTILE_YAML[kind](path.read_bytes()))

    with pytest.raises(AgentsConfigError):
        load_agents_config(path=path)
