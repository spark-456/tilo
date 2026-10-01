"""P0-08b-player: FR-WLD-10 / BQ-08 acceptance test for the synthetic crowd perf fixture.

Ticket text: "a deterministic seeded Node script (apps/web/scripts/make-crowd-fixture.mjs, agent
count as an argument) into apps/web/fixtures/ (crowd-20.layout.json, crowd-20.events.jsonl) and
validated by a pytest test ... against contracts/layout.schema.json, contracts/event.schema.json
and each type's data schema, with strictly increasing seq, tier vs agent count (PRD 9.1) and
layout limits (<= 6 districts per level, <= 5 buildings per district)."

This test validates the *generated fixture files already committed* under apps/web/fixtures/
(crowd-20.layout.json / crowd-20.events.jsonl), it does not itself run the generator script —
apps/web/scripts/make-crowd-fixture.mjs is Node tooling, out of scope for a Python test. See
apps/web/e2e/world-perf.spec.ts for the FR-WLD-10 perf assertion (fps under CPU throttling)
that actually consumes this fixture in a browser.

Run with `uv run pytest tests/web -q` (jsonschema, referencing and pyyaml are root dev
dependencies; see pyproject.toml, same as tests/contracts).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema
import pytest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
FIXTURES_DIR = REPO_ROOT / "apps" / "web" / "fixtures"

LAYOUT_PATH = FIXTURES_DIR / "crowd-20.layout.json"
EVENTS_PATH = FIXTURES_DIR / "crowd-20.events.jsonl"

# PRD 9.1 tier table (also contracts/common.schema.json#/$defs/tier's description).
TIER_BOUNDS = [
    ("outpost", 1, 2),
    ("village", 3, 6),
    ("town", 7, 15),
    ("city", 16, float("inf")),
]


def _build_registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(CONTRACTS_DIR.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def _validator(schema: dict[str, Any], registry: Registry) -> jsonschema.protocols.Validator:
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    cls.check_schema(schema)
    return cls(schema, registry=registry)


def _errors(schema: dict[str, Any], instance: Any, registry: Registry) -> list[str]:
    validator = _validator(schema, registry)
    return [str(e) for e in validator.iter_errors(instance)]


@pytest.fixture(scope="module")
def registry() -> Registry:
    return _build_registry()


@pytest.fixture(scope="module")
def layout() -> dict[str, Any]:
    assert LAYOUT_PATH.is_file(), (
        f"{LAYOUT_PATH} is missing — run `node apps/web/scripts/make-crowd-fixture.mjs 20` from apps/web/"
    )
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def events() -> list[dict[str, Any]]:
    assert EVENTS_PATH.is_file(), (
        f"{EVENTS_PATH} is missing — run `node apps/web/scripts/make-crowd-fixture.mjs 20` from apps/web/"
    )
    lines = [line for line in EVENTS_PATH.read_text(encoding="utf-8").split("\n") if line.strip()]
    return [json.loads(line) for line in lines]


def test_FR_WLD_10_crowd_fixture_layout_matches_layout_schema(layout: dict[str, Any], registry: Registry) -> None:
    schema = json.loads((CONTRACTS_DIR / "layout.schema.json").read_text(encoding="utf-8"))
    errors = _errors(schema, layout, registry)
    assert errors == [], "\n".join(errors)


def test_FR_WLD_10_crowd_fixture_events_match_event_schema_and_data_schemas(
    events: list[dict[str, Any]], registry: Registry
) -> None:
    event_schema = json.loads((CONTRACTS_DIR / "event.schema.json").read_text(encoding="utf-8"))
    registry_yaml = __import__("yaml").safe_load(
        (CONTRACTS_DIR / "events" / "registry.yaml").read_text(encoding="utf-8")
    )
    data_schema_cache: dict[str, dict[str, Any]] = {}
    all_errors: list[str] = []

    for event in events:
        errors = _errors(event_schema, event, registry)
        if errors:
            all_errors.append(f"seq={event.get('seq')} type={event.get('type')}: {errors}")
            continue

        event_type = event["type"]
        entry = registry_yaml["types"].get(event_type)
        assert entry is not None, f"seq={event['seq']}: {event_type} is not in the event registry"

        schema_rel = entry["data_schema"]
        if schema_rel not in data_schema_cache:
            data_schema_cache[schema_rel] = json.loads((CONTRACTS_DIR / schema_rel).read_text(encoding="utf-8"))
        data_errors = _errors(data_schema_cache[schema_rel], event["data"], registry)
        if data_errors:
            all_errors.append(f"seq={event['seq']} type={event_type} data: {data_errors}")

    assert all_errors == [], "\n".join(all_errors)


def test_FR_WLD_10_crowd_fixture_seq_strictly_increasing(events: list[dict[str, Any]]) -> None:
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs), "seq is not sorted ascending"
    assert len(seqs) == len(set(seqs)), "seq has duplicates"
    for a, b in zip(seqs, seqs[1:]):
        assert b == a + 1, f"seq jumps from {a} to {b} (must be strictly increasing by 1)"


def test_FR_WLD_10_crowd_fixture_tier_matches_agent_count(layout: dict[str, Any]) -> None:
    agent_count = len(layout["semantic"]["agents"])
    tier = layout["tier"]
    matching = [name for name, lo, hi in TIER_BOUNDS if lo <= agent_count <= hi]
    assert matching == [tier], (
        f"{agent_count} agents should map to tier {matching}, layout says tier={tier!r} "
        f"(PRD 9.1 outpost 1-2, village 3-6, town 7-15, city 16+)"
    )
    assert agent_count >= 16, "the perf fixture (P9) is meant to stress a city-tier crowd (16+ agents)"


def test_FR_WLD_10_crowd_fixture_layout_limits(layout: dict[str, Any]) -> None:
    for level in layout["semantic"]["levels"]:
        districts = level["districts"]
        assert len(districts) <= 6, f"level {level['id']} has {len(districts)} districts (max 6)"
        for district in districts:
            buildings = district["buildings"]
            assert len(buildings) <= 5, f"district {district['id']} has {len(buildings)} buildings (max 5)"


def test_FR_WLD_10_crowd_fixture_all_agents_but_the_director_move_at_least_once(
    layout: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    movers = {e["actor"] for e in events if e["type"] == "agent.moved"}
    non_director_agents = {a["id"] for a in layout["semantic"]["agents"] if a["rank"] != "director"}
    missing = non_director_agents - movers
    assert missing == set(), f"agents with no agent.moved event: {sorted(missing)}"
