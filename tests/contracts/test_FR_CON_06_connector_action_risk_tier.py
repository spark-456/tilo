"""FR-CON-06 (PRD 12.1, ticket P0-02 section 1 connector.schema.json): "Every
connector action declares a risk tier; the policy engine enforces it." Lint
fails on an action without a tier."

Ticket's rule test: "a connector action without a risk tier is invalid."
`connector.schema.json`'s `actions` field is described as "each action with
its risk tier (T1-T3, section 10.4) and its gate type" -- ticket section 1:
"actions each with risk_tier and gate_type (required)".
"""

from __future__ import annotations

import copy

import pytest
from _lib import errors_for, list_fixtures, load_json, load_schema


@pytest.fixture()
def a_valid_connector(repo_root):
    fixtures = list_fixtures(repo_root, "connector", "valid")
    assert fixtures, "FR-CON-06: need at least one contracts/fixtures/connector/valid/*.json to mutate"
    instance = load_json(fixtures[0])
    assert instance.get("actions"), (
        f"FR-CON-06: the valid connector fixture {fixtures[0].name} must have at least one action "
        "in 'actions' to mutate"
    )
    assert "risk_tier" in instance["actions"][0], (
        f"FR-CON-06: the valid connector fixture {fixtures[0].name}'s first action must have a "
        "'risk_tier' field to remove"
    )
    return instance


def test_FR_CON_06_connector_action_without_risk_tier_is_invalid(repo_root, registry, a_valid_connector):
    schema = load_schema(repo_root, "connector")
    mutated = copy.deepcopy(a_valid_connector)
    del mutated["actions"][0]["risk_tier"]
    errors = errors_for(schema, mutated, registry)
    assert errors, "FR-CON-06: a connector action without risk_tier must be invalid"


def test_FR_CON_06_connector_with_every_action_tiered_is_valid(repo_root, registry, a_valid_connector):
    schema = load_schema(repo_root, "connector")
    errors = errors_for(schema, a_valid_connector, registry)
    assert not errors, (
        f"FR-CON-06: a connector whose every action has a risk_tier should validate, got: {[e.message for e in errors]}"
    )
