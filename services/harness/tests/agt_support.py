"""Shared, non-test support for the FR-AGT-01/02/03 acceptance tests (P2 harness executor,
docs/parallel-sessions.md session SH). Not a test module itself (no `test_` prefix), so pytest
never collects it; every `test_FR_AGT_0*_*.py` / `test_D_11_p0_09_followups.py` file in this
directory imports from it.

`tilo_harness.config` / `.executor` / `.skills` do not exist yet, same as `tilo_harness` itself
did not exist for the P0-09 skeleton tests: every helper here that touches one of those modules
imports it lazily (inside the function, not at module import time), so this file itself always
imports cleanly and each test file's own top-level import is what fails with the expected
ImportError until the builder lands the ticket.

Contract self-check: `contract_errors`/`assert_valid_contract` load every contracts/*.schema.json
the same way `tilo_harness.validator._load_schemas` does (root CLAUDE.md: a service must not
import from scripts/, but this is test-only code, and the ticket brief asks fixtures to be
"validated against the contracts in the tests themselves") so every plan/layout/skill fixture
built below is checked against plan.schema.json / layout.schema.json / skill.schema.json /
agents.schema.json directly, not just trusted by construction.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_providers.fake import FakeModelProvider  # always available: packages/providers is already built

TESTS_DIR = Path(__file__).resolve().parent
HARNESS_DIR = TESTS_DIR.parent
REPO_ROOT = HARNESS_DIR.parent.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"
SKILLS_FIXTURES_DIR = TESTS_DIR / "fixtures" / "skills"
INVALID_SKILLS_FIXTURES_DIR = TESTS_DIR / "fixtures" / "skills_invalid"


# ---------------------------------------------------------------------------
# contracts/*.schema.json self-check (plan, layout, skill, agents, envelope, ...)
# ---------------------------------------------------------------------------


def _load_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for path in sorted(CONTRACTS_DIR.glob("**/*.schema.json")):
        rel = path.relative_to(CONTRACTS_DIR)
        if "fixtures" in rel.parts:
            continue
        schemas[rel.as_posix().removesuffix(".schema.json")] = json.loads(path.read_text(encoding="utf-8"))
    return schemas


_SCHEMAS = _load_schemas()
_REGISTRY = Registry().with_resources(
    (schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)) for schema in _SCHEMAS.values()
)


def contract_errors(schema_key: str, instance: Any) -> list[str]:
    """Every jsonschema error message for `instance` against contracts/<schema_key>.schema.json
    (e.g. schema_key="plan", "layout", "skill", "agents")."""
    validator = jsonschema.Draft202012Validator(_SCHEMAS[schema_key], registry=_REGISTRY)
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in validator.iter_errors(instance)]


def assert_valid_contract(schema_key: str, instance: Any) -> None:
    errors = contract_errors(schema_key, instance)
    assert not errors, f"{schema_key}.schema.json violations: {errors}"


# ---------------------------------------------------------------------------
# Layout / plan builders -- kept generic so each test file states only what varies
# ---------------------------------------------------------------------------


def build_layout(
    *,
    world_id: str = "w_agt_test",
    tier: str = "village",
    theme: str = "metropolis",
    district_specs: list[dict[str, Any]],
    director_id: str | None = "A_dir",
    extra_agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`district_specs`: one dict per district --
    {"id": "D1", "lead": "A_lead1", "specialists": ["A_s1", ...], "unit_ids": ["U1", ...]}.
    Every unit's building is the district's single "common" workshop building (plan_units may be
    empty -- layout.schema.json only requires plan_units when a building is a "kit", not "common").
    `extra_agents` lets a test add agents deliberately NOT wired into any district (e.g. an extra
    director, or a specialist-rank agent with no district) for the layout-shortage tests."""
    agents: list[dict[str, Any]] = []
    if director_id is not None:
        agents.append({"id": director_id, "rank": "director"})
    districts: list[dict[str, Any]] = []
    for spec in district_specs:
        # `skip_auto_lead_agent`: the district's "lead" field is still set (layout.schema.json
        # requires it), but no rank="lead" agent entry is auto-added for it -- lets a test put
        # that id in `extra_agents` with a different rank instead (the "district lead id points
        # at a non-lead-rank agent" layout-shortage case).
        if spec.get("lead") is not None and not spec.get("skip_auto_lead_agent"):
            agents.append({"id": spec["lead"], "rank": "lead"})
        for specialist_id in spec.get("specialists", []):
            agents.append({"id": specialist_id, "rank": "specialist"})
        districts.append(
            {
                "id": spec["id"],
                "name": spec.get("name", "Ops"),
                "icon": "inbox",
                "lead": spec["lead"],
                "buildings": [
                    {
                        "id": spec.get("building_id", "B1"),
                        "name": spec.get("building_name", "Workshop"),
                        "kind": "common",
                        "common_type": "workshop",
                        "plan_units": spec.get("unit_ids", []),
                    }
                ],
            }
        )
    if extra_agents:
        agents.extend(extra_agents)
    layout = {
        "v": "1.0",
        "world_id": world_id,
        "tier": tier,
        "theme": theme,
        "semantic": {
            "levels": [{"id": "L1", "name": "Level One", "districts": districts}],
            "islands": [],
            "gates": [],
            "agents": agents,
        },
        "geometry": None,
    }
    assert_valid_contract("layout", layout)
    return layout


def build_approaches() -> list[dict[str, Any]]:
    """Two approaches differing on >= 2 of the 5 dimensions (plan.rules.md PG-08), reused by
    every `build_plan` call below: this ticket's tests exercise the executor, not the planner, so
    the approaches themselves only need to keep the plan schema-valid."""
    return [
        {
            "id": "quick",
            "label": "Quick",
            "summary": "One fast overview pass.",
            "dimensions": {
                "depth": "overview",
                "sources": 1,
                "parallelism": 1,
                "verification": "basic",
                "output_format": "in_app",
            },
            "time": {"min_s": 60, "max_s": 300},
            "credits": {"min": 1, "max": 5},
            "risks": [],
            "skips": [],
        },
        {
            "id": "thorough",
            "label": "Thorough",
            "summary": "A deep, verified pass.",
            "dimensions": {
                "depth": "deep",
                "sources": 5,
                "parallelism": 4,
                "verification": "thorough",
                "output_format": "in_app",
            },
            "time": {"min_s": 300, "max_s": 1200},
            "credits": {"min": 5, "max": 20},
            "risks": [],
            "skips": [],
        },
    ]


def build_unit(
    unit_id: str,
    *,
    role: str = "specialist",
    district: str = "D1",
    depends_on: list[str] | None = None,
    skills: list[str] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    return {
        "id": unit_id,
        "unit_type": "research",
        "title": title or f"Unit {unit_id}",
        "role": role,
        "district": district,
        "skills": skills or [],
        "connectors": [],
        "actions": [],
        "depends_on": depends_on or [],
    }


def build_plan(units: list[dict[str, Any]], *, budget_cap: float = 10.0, chosen: str = "quick") -> dict[str, Any]:
    plan = {
        "approaches": build_approaches(),
        "chosen_approach": chosen,
        "units": units,
        "gates": [],
        "budget_cap": budget_cap,
    }
    assert_valid_contract("plan", plan)
    return plan


# ---------------------------------------------------------------------------
# config/agents.yaml -- tests write their own temp file rather than editing the real
# config/agents.yaml (config/ is owned by session S0, docs/parallel-sessions.md)
# ---------------------------------------------------------------------------


def default_agents_config_dict(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "limits": {"directors_per_world": 1, "leads_per_district": 1, "max_specialists": 3, "max_depth": 3},
        "context": {"compact_at": 0.6, "handoff_at": 0.7},
        "liveness": {"heartbeat_s": 15, "silent_after_s": 90},
        "retries": {"max_attempts": 3},
        "questions": {"hourly_cap_per_person": 6},
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return base


def write_agents_config(path: Path, **overrides: Any) -> Path:
    """Writes a schema-valid (unless a test deliberately breaks it) agents.yaml at `path`."""
    data = default_agents_config_dict(**overrides)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def load_config_sync(path: Path) -> Any:
    from tilo_harness.config import load_agents_config

    return load_agents_config(path=path)


# ---------------------------------------------------------------------------
# Skill fixtures -- copy the committed fixture tree into a tmp_path so a test can mutate a
# skill's files on disk without touching the committed fixtures (FR-AGT-03 mid-run change test).
# ---------------------------------------------------------------------------


def copy_skills_fixture_tree(dest: Path) -> Path:
    shutil.copytree(SKILLS_FIXTURES_DIR, dest, dirs_exist_ok=True)
    return dest


def make_skill_registry(root: Path) -> Any:
    from tilo_harness.skills import SkillRegistry

    return SkillRegistry(root)


# ---------------------------------------------------------------------------
# UnitRunner test double (ticket brief item 3): records each unit's start/end so a test can
# measure concurrency deterministically via asyncio coordination, never a wall-clock sleep.
# ---------------------------------------------------------------------------


class RecordingRunner:
    """`UnitRunner` double: `async def run(self, unit, context) -> UnitOutcome`.

    `release_immediately=True` (the default): each unit finishes as soon as it starts, after one
    real `await` (so the event loop still gets a chance to interleave concurrent units) -- good
    enough to prove *ordering* (chain/diamond) without any manual gating.

    `release_immediately=False`: a unit's `run()` blocks on a shared `asyncio.Event` until the
    test calls `release_all()`, so the test can poll `in_flight`/`max_in_flight` while several
    units are deliberately held open at once -- this is what proves a concurrency *cap*.
    """

    def __init__(self, *, release_immediately: bool = True, fail_unit_ids: frozenset[str] = frozenset()) -> None:
        self.starts: list[str] = []
        self.ends: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._release_immediately = release_immediately
        self._release_all = asyncio.Event()
        self._fail_unit_ids = fail_unit_ids

    async def run(self, unit: dict[str, Any], context: Any) -> Any:
        from tilo_harness.executor import UnitOutcome

        unit_id = unit["id"]
        self.starts.append(unit_id)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        if self._release_immediately:
            await asyncio.sleep(0)  # still a real yield point, so concurrent units can interleave
        else:
            await self._release_all.wait()
        self.in_flight -= 1
        self.ends.append(unit_id)
        return UnitOutcome(success=unit_id not in self._fail_unit_ids)

    def release_all(self) -> None:
        self._release_all.set()


async def wait_until(predicate: Any, *, max_iterations: int = 10_000) -> None:
    """Cooperative-yield poll (`asyncio.sleep(0)`, never a wall-clock sleep) until `predicate()`
    is true, so a test can deterministically wait for `runner.in_flight` to reach a value while
    `run_plan` runs concurrently as a task in the same event loop."""
    for _ in range(max_iterations):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError(f"wait_until: predicate never became true within {max_iterations} cooperative yields")


class CountingFakeModelProvider(FakeModelProvider):
    """A real `FakeModelProvider` (subclassing `ModelProvider`, so any `isinstance` check the
    default runner makes still holds; no network, no paid call, EFF-01) that also counts
    `.generate()`/`.stream()` calls, so a test can prove the default `UnitRunner` actually called
    a model *through the provider layer, by role* (PL-01: business code never names a model id)
    without depending on FakeModelProvider's exact canned output."""

    def __init__(self, profile_id: str) -> None:
        super().__init__(profile_id=profile_id)
        self.calls: list[Any] = []

    def generate(self, request: Any) -> Any:
        self.calls.append(request)
        return super().generate(request)

    def stream(self, request: Any) -> Any:
        self.calls.append(request)
        return super().stream(request)


def run_plan_sync(*args: Any, **kwargs: Any) -> Any:
    """`run_plan` is `async def` (PRD 8.1: "the executor is asyncio in one thread"; also the only
    way a test can poll a `RecordingRunner`'s concurrency *while* a run is in flight, per the
    ticket brief's "asyncio events, not wall-clock sleeps" -- a synchronous `run_plan` wrapping
    its own `asyncio.run()` would make that impossible without threads). Tests that do not need
    to observe mid-run state use this synchronous wrapper instead of repeating `asyncio.run(...)`."""
    from tilo_harness.executor import run_plan

    return asyncio.run(run_plan(*args, **kwargs))
