"""FR-INT-10 prerequisite (issue #124): jsonschema's `uniqueItems` compares every pair when the items
are unsortable, so a plan with 100 gates x 200 dicts in `guards` took 29 s inside the maxItems caps.
Its `uniqueItems` is now linear (`tilo_providers.schema_guard`, #173), so a non-string item there is a
`schema` violation found at once."""

from __future__ import annotations

import copy
import json
import time
from typing import Any

import pytest
from _plan_validator_lib import make_gate, make_plan, make_unit, rule_ids
from tilo_planning.plangraph import CONTRACTS, validate_plan

NOW = "2026-10-01T00:00:00.000Z"
LIMIT_S = 1.0


def _run(plan, risk_table, fake_connectors, fake_skills, fake_policies):
    return validate_plan(
        plan, risk_table=risk_table, connectors=fake_connectors, skills=fake_skills, policies=fake_policies, now=NOW
    )


def _unique_arrays() -> list[tuple[str, str]]:
    """(collection, field) of every uniqueItems property of any plan.schema.json def, read from it."""
    schema = json.loads((CONTRACTS / "plan.schema.json").read_text("utf-8"))
    collections = {"unit": "units", "gate": "gates"}
    return [
        (collections.get(name, name), field)
        for name, definition in schema["$defs"].items()
        for field, prop in definition.get("properties", {}).items()
        if prop.get("uniqueItems")
    ]


def _small_plan() -> dict[str, Any]:
    units = [make_unit("U1", connectors=("gmail",), actions=("send_email",)), make_unit("U2", depends_on=("U1",))]
    return make_plan(units, [make_gate("G1", "send_email", ["U1"], "T3", None)])


def test_FR_INT_10_the_schema_has_the_unique_arrays_the_guard_covers() -> None:
    assert sorted(_unique_arrays()) == [
        ("gates", "guards"),
        ("units", "actions"),
        ("units", "connectors"),
        ("units", "depends_on"),
        ("units", "skills"),
    ]


def test_FR_INT_10_100_gates_x_200_dict_guards_rejected_in_under_a_second(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    """At 100 x 200 the plan is over the byte cap (#173); 20 x 200 is under it and reaches the schema."""
    for gate_count, units_count in ((100, 200), (20, 20)):
        units = [make_unit(f"U{i}") for i in range(units_count)]
        gates = [make_gate(f"G{g}", "send_email", [], "T3", None) for g in range(gate_count)]
        for g, gate in enumerate(gates):
            gate["guards"] = [{"k": g * 1000 + i} for i in range(200)]
        started = time.perf_counter()
        violations = _run(make_plan(units, gates), risk_table, fake_connectors, fake_skills, fake_policies)
        assert time.perf_counter() - started < LIMIT_S
        assert rule_ids(violations) == {"schema"}
    assert any("/gates/0/guards/0" in v.message and "string" in v.message for v in violations)


@pytest.mark.parametrize("bad", [{"k": 1}, ["U1"], 7, None, True], ids=["dict", "list", "int", "null", "bool"])
@pytest.mark.parametrize(("collection", "field"), _unique_arrays())
def test_FR_INT_10_non_string_item_in_any_unique_array_is_schema(
    collection, field, bad, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    plan = _small_plan()
    plan[collection][0][field] = [*plan[collection][0][field], bad]
    index = len(plan[collection][0][field]) - 1
    violations = _run(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert rule_ids(violations) == {"schema"}
    assert any(f"/{collection}/0/{field}/{index}" in v.message for v in violations)


def test_FR_INT_10_valid_plan_still_passes(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    assert _run(_small_plan(), risk_table, fake_connectors, fake_skills, fake_policies) == []


def test_FR_INT_10_valid_fixture_plan_still_passes(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    path = CONTRACTS / "fixtures" / "plan" / "valid" / "three_approaches_policy_gate.json"
    plan = json.loads(path.read_text("utf-8"))
    assert _run(plan, risk_table, fake_connectors, fake_skills, fake_policies) == []


@pytest.mark.parametrize(("collection", "field"), _unique_arrays())
def test_FR_INT_10_duplicate_string_ids_still_rejected(
    collection, field, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    plan = _small_plan()
    plan[collection][0][field] = ["U1", "U1"] if field in ("guards", "depends_on") else ["dup_id", "dup_id"]
    violations = _run(copy.deepcopy(plan), risk_table, fake_connectors, fake_skills, fake_policies)
    assert "schema" in rule_ids(violations)
    assert any(f"/{collection}/0/{field}" in v.message and "non-unique" in v.message for v in violations)
