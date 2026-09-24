"""FR-INT-03 (PRD 7.1, ticket P0-02 section 1 brief.schema.json): "The Director
extracts a schema-valid brief: goal, deliverables, audience, deadline,
constraints, sources, sensitivity."

Ticket's rule test: "a brief missing any of goal, deliverables, audience,
deadline, constraints, sources, sensitivity is invalid." `deadline` is
"nullable" (PRD 7.1 / ticket section 1), so the key must still be present
(value may be `null`) -- this test removes the *key*, not just its value.

Starts from an existing valid fixture and deletes one required key at a time,
rather than hand-building a brief instance, so it does not depend on guessing
any field this ticket's schema needs beyond the seven FR-INT-03 names.
"""

from __future__ import annotations

import copy

import pytest
from _lib import errors_for, list_fixtures, load_json, load_schema

REQUIRED_FIELDS = (
    "goal",
    "deliverables",
    "audience",
    "deadline",
    "constraints",
    "sources",
    "sensitivity",
)


@pytest.fixture()
def a_valid_brief(repo_root):
    fixtures = list_fixtures(repo_root, "brief", "valid")
    assert fixtures, "FR-INT-03: need at least one contracts/fixtures/brief/valid/*.json to mutate"
    instance = load_json(fixtures[0])
    for field in REQUIRED_FIELDS:
        assert field in instance, (
            f"FR-INT-03: the valid brief fixture {fixtures[0].name} is missing {field!r}, so this "
            "test cannot isolate the missing-field rule from a fixture that is already broken"
        )
    return instance


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_FR_INT_03_brief_missing_required_field_is_invalid(repo_root, registry, a_valid_brief, field):
    schema = load_schema(repo_root, "brief")
    mutated = copy.deepcopy(a_valid_brief)
    del mutated[field]
    errors = errors_for(schema, mutated, registry)
    assert errors, f"FR-INT-03: a brief missing {field!r} must be invalid against brief.schema.json"


def test_FR_INT_03_brief_with_every_required_field_is_valid(repo_root, registry, a_valid_brief):
    schema = load_schema(repo_root, "brief")
    errors = errors_for(schema, a_valid_brief, registry)
    assert (
        not errors
    ), f"FR-INT-03: a brief with every required field present should validate, got: {[e.message for e in errors]}"
