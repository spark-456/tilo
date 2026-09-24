"""FR-INT-06 (PRD 7.1, ticket P0-02 section 1 plan.schema.json): "2-3
approaches that differ on at least 2 of 5 dimensions ..., each with time
range, credit range, risks and what it skips."

Ticket's rule test: "a plan offers 2 to 3 approaches." This mutates the
`approaches` array of an existing valid plan fixture (shrinking to 1, growing
to 4 by duplicating an entry) rather than hand-building a plan instance,
since the schema's exact field names for each approach's cost/time/risk data
are the builder's choice; only the *count* is specified by FR-INT-06.
"""

from __future__ import annotations

import copy

import pytest
from _lib import errors_for, list_fixtures, load_json, load_schema


@pytest.fixture()
def a_valid_plan(repo_root):
    fixtures = list_fixtures(repo_root, "plan", "valid")
    assert fixtures, "FR-INT-06: need at least one contracts/fixtures/plan/valid/*.json to mutate"
    instance = load_json(fixtures[0])
    assert (
        "approaches" in instance
    ), f"FR-INT-06: the valid plan fixture {fixtures[0].name} has no top-level 'approaches' array"
    assert 2 <= len(instance["approaches"]) <= 3, (
        f"FR-INT-06: the valid plan fixture {fixtures[0].name} itself must offer 2 to 3 approaches, "
        f"got {len(instance['approaches'])}"
    )
    return instance


def test_FR_INT_06_one_approach_is_invalid(repo_root, registry, a_valid_plan):
    schema = load_schema(repo_root, "plan")
    mutated = copy.deepcopy(a_valid_plan)
    mutated["approaches"] = mutated["approaches"][:1]
    errors = errors_for(schema, mutated, registry)
    assert errors, "FR-INT-06: a plan with 1 approach must be invalid (2-3 required)"


def test_FR_INT_06_four_approaches_is_invalid(repo_root, registry, a_valid_plan):
    schema = load_schema(repo_root, "plan")
    mutated = copy.deepcopy(a_valid_plan)
    approaches = mutated["approaches"]
    # Duplicate entries (with distinct ids where present) until there are 4.
    while len(approaches) < 4:
        clone = copy.deepcopy(approaches[len(approaches) % len(a_valid_plan["approaches"])])
        if isinstance(clone, dict) and "id" in clone:
            clone["id"] = f"{clone['id']}_dup{len(approaches)}"
        approaches.append(clone)
    errors = errors_for(schema, mutated, registry)
    assert errors, "FR-INT-06: a plan with 4 approaches must be invalid (2-3 required)"


def test_FR_INT_06_two_or_three_approaches_is_valid(repo_root, registry, a_valid_plan):
    schema = load_schema(repo_root, "plan")
    errors = errors_for(schema, a_valid_plan, registry)
    assert not errors, (
        f"FR-INT-06: a plan with {len(a_valid_plan['approaches'])} approaches (2-3) should validate, "
        f"got: {[e.message for e in errors]}"
    )
