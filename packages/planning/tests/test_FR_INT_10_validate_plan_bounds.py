"""FR-INT-10 prerequisite (issue #173): `validate_plan` will take client plan JSON, so its cost is bounded
(byte cap BQ-107, inlined `$ref`s, MAX_ERRORS, capped messages), and every `uniqueItems` the plan validator
and the router meet is linear (`tilo_providers.schema_guard`)."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _plan_validator_lib import make_gate, make_plan, make_unit, rule_ids
from tilo_planning import approaches, brief, plangraph
from tilo_planning.plangraph import MAX_PLAN_BYTES, MAX_PLAN_DEPTH, Violation, validate_plan
from tilo_providers import conformance, schema_guard
from tilo_providers.schema_guard import MAX_ERRORS, MESSAGE_CHARS

NOW = "2026-10-01T00:00:00.000Z"
LIMIT_S = 1.0
REPO = Path(__file__).resolve().parents[3]
TOO_BIG = [Violation("schema", f"/: the plan is larger than {MAX_PLAN_BYTES} bytes")]


@pytest.fixture()
def registries(risk_table, fake_connectors, fake_skills, fake_policies) -> dict[str, Any]:
    return {"risk_table": risk_table, "connectors": fake_connectors, "skills": fake_skills, "policies": fake_policies}


def _timed(plan: Any, registries: dict[str, Any]) -> tuple[list[Violation], float]:
    started = time.perf_counter()
    violations = validate_plan(plan, **registries, now=NOW)
    return violations, time.perf_counter() - started


def _size(plan: Any) -> int:
    return len(json.dumps(plan, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _max_plan(unit_id: Any = "U{}".format) -> dict[str, Any]:
    """Every array at its cap (#173: 261 KiB, 29k ids); `unit_id(i)` names unit i wherever it appears."""
    words = [f"x{k}" for k in range(10)]
    units = [make_unit(f"U{i}", skills=words, connectors=words, actions=words) for i in range(200)]
    for i, unit in enumerate(units):
        unit["id"], unit["depends_on"] = unit_id(i), [unit_id(j) for j in range(50)]
    guards = [unit_id(i) for i in range(200)]
    return make_plan(units, [make_gate(f"G{g}", "x0", guards, "T3", None) for g in range(100)])


@pytest.mark.parametrize("unit_id", ["U{}".format, "bad unit {}".format], ids=["valid_max", "36k_errors"])
def test_FR_INT_10_plan_over_the_byte_cap_rejected_in_under_a_second(unit_id, registries) -> None:
    plan = _max_plan(unit_id)
    assert _size(plan) > 240 * 1024
    violations, elapsed = _timed(plan, registries)
    assert elapsed < LIMIT_S
    assert violations == TOO_BIG


def test_FR_INT_10_36k_error_plan_stops_at_the_error_cap_without_the_byte_cap(registries, monkeypatch) -> None:
    monkeypatch.setattr(plangraph, "MAX_PLAN_BYTES", 10**9)
    violations, elapsed = _timed(_max_plan("bad unit {}".format), registries)
    assert elapsed < LIMIT_S
    assert len(violations) == MAX_ERRORS
    assert rule_ids(violations) == {"schema"}


def test_FR_INT_10_largest_valid_plan_under_the_byte_cap_passes_in_under_a_second(registries) -> None:
    units = [make_unit(f"U{i}", title="t" * 80) for i in range(200)]
    plan = make_plan(units, [])
    size = _size(plan)
    for i in range(1, 200):  # each unit depends on as many earlier units as the cap allows
        for j in range(i - 1, max(i - 51, -1), -1):
            extra = len(f'"U{j}"') + bool(units[i]["depends_on"])  # the id and its comma
            if size + extra > MAX_PLAN_BYTES:
                break
            units[i]["depends_on"].append(f"U{j}")
            size += extra
    assert MAX_PLAN_BYTES - 64 < _size(plan) == size <= MAX_PLAN_BYTES
    violations, elapsed = _timed(plan, registries)
    assert violations == []
    assert elapsed < LIMIT_S


@pytest.mark.parametrize("depth", [100, 500, 990])
@pytest.mark.parametrize("kind", ["list", "dict"])
def test_FR_INT_10_deeply_nested_plan_under_the_byte_cap_is_schema_in_under_a_second(kind, depth, registries) -> None:
    """Measuring bytes costs bytes x depth (#192 review): many small values under deep nesting, under 64 KiB."""
    plan = make_plan([make_unit("U1")], [])
    room = MAX_PLAN_BYTES - 16 - (_size(plan) - len('"Unit U1"')) - depth * (2 if kind == "list" else len('{"a":}'))
    nested: Any = [0] * ((room - 1) // 2)  # "[0,0,...]" is 2n + 1 bytes
    for _ in range(depth):
        nested = [nested] if kind == "list" else {"a": nested}
    plan["units"][0]["title"] = nested
    violations, elapsed = _timed(plan, registries)
    assert elapsed < LIMIT_S
    assert violations == [Violation("schema", f"/: the plan is nested deeper than {MAX_PLAN_DEPTH} levels")]


def test_FR_INT_10_a_long_bad_value_is_truncated_in_its_violation(registries) -> None:
    plan = make_plan([make_unit("U" + "9" * 30_000)], [])
    violations, _ = _timed(plan, registries)
    assert violations
    assert all(len(v.message) <= MESSAGE_CHARS for v in violations)
    assert violations[0].message.startswith("/units/0/id: ")


# --- every uniqueItems the plan validator and the router meet is the linear one ---------------------


def _nodes(schema: Any) -> Iterator[dict[str, Any]]:
    if isinstance(schema, dict):
        yield schema
        for value in schema.values():
            yield from _nodes(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _nodes(value)


def _assert_linear(root_validator: Any, schema: dict[str, Any]) -> int:
    """Each uniqueItems array (without its linear `items`) reports 3000 dicts and a duplicate in under a
    second; no subschema declares `$schema`, which would swap in a stock validator class."""
    assert not any("$schema" in node for node in _nodes(schema))
    unique = [node for node in _nodes(schema) if node.get("uniqueItems") is True]
    items = [{"k": i} for i in range(3000)] + [{"k": 0}]
    for node in unique:
        array_only = {key: value for key, value in node.items() if key != "items"}
        started = time.perf_counter()
        errors = list(root_validator.evolve(schema=array_only).iter_errors(items))
        assert time.perf_counter() - started < LIMIT_S, node
        assert any(error.validator == "uniqueItems" for error in errors), node
    return len(unique)


def test_FR_INT_10_every_unique_array_in_the_plan_schema_is_linear() -> None:
    validator = plangraph._plan_validator()
    assert not any("$ref" in node for node in _nodes(validator.schema))
    assert _assert_linear(validator, validator.schema) == 5  # units: skills, connectors, actions, depends_on; guards


_ROUTER_SCHEMAS = {
    "packages/planning/src/tilo_planning/approaches.py": approaches._Reply.model_json_schema(),
    "packages/planning/src/tilo_planning/brief.py": brief.output_schema(),
    "packages/providers/src/tilo_providers/conformance.py": conformance._SCHEMA,
}


def test_PL_03_every_unique_array_in_every_router_response_schema_is_linear() -> None:
    found = {
        path.relative_to(REPO).as_posix()
        for top in ("packages", "services")
        for path in (REPO / top).glob("*/src/**/*.py")
        if re.search(r"\bresponse_schema=(?!\.\.\.)", path.read_text("utf-8"))
    }
    assert found == set(_ROUTER_SCHEMAS)  # a new response_schema is listed here
    assert sum(_assert_linear(schema_guard.validator(s), s) for s in _ROUTER_SCHEMAS.values()) >= 1
