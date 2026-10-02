"""FR-INT-09 (PRD 7.1; contracts/plan.schema.json, contracts/plan.rules.md): "A deterministic
validator checks the PlanGraph against plan.schema.json and plan.rules.md before a plan reaches a
person; a plan that fails any check is rejected." This file exercises `validate_plan` against
every committed contract fixture in `contracts/fixtures/plan/{valid,invalid}/`: each valid fixture
must validate cleanly, each invalid one must be rejected.

Every fixture under `contracts/fixtures/plan/invalid/` fails at the `plan.schema.json` shape level
(missing a required field, an out-of-range value, or an enum violation -- see each fixture's name)
rather than a `plan.rules.md` cross-reference rule, including `PG-12` ("2 to 3 approaches, at
least one unit, a positive budget cap"), which `plan.rules.md` itself marks "(schema)". So this
file asserts only that `validate_plan` rejects them (non-empty violations), not a specific PG id;
the PG-id-specific rules get their own fixtures in `test_FR_INT_09_plan_graph_rules.py`.
"""

from __future__ import annotations

import pytest
from _plan_validator_lib import list_plan_fixtures, load_plan_fixture
from tilo_planning.plangraph import validate_plan

VALID_FIXTURES = list_plan_fixtures("valid")
INVALID_FIXTURES = list_plan_fixtures("invalid")


def test_FR_INT_09_fixture_dirs_are_not_empty() -> None:
    """Sanity check so a typo in `list_plan_fixtures` can't silently parametrize 0 cases."""
    assert VALID_FIXTURES, "contracts/fixtures/plan/valid/ has no fixtures"
    assert INVALID_FIXTURES, "contracts/fixtures/plan/invalid/ has no fixtures"


@pytest.mark.parametrize("name", VALID_FIXTURES)
def test_FR_INT_09_valid_plan_fixtures_pass(name, risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    plan = load_plan_fixture("valid", name)
    violations = validate_plan(
        plan, risk_table=risk_table, connectors=fake_connectors, skills=fake_skills, policies=fake_policies
    )
    assert violations == [], f"{name}: expected a valid plan, got {[v.rule_id for v in violations]}"


@pytest.mark.parametrize("name", INVALID_FIXTURES)
def test_FR_INT_09_invalid_plan_fixtures_fail(name, risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    plan = load_plan_fixture("invalid", name)
    violations = validate_plan(
        plan, risk_table=risk_table, connectors=fake_connectors, skills=fake_skills, policies=fake_policies
    )
    assert violations != [], f"{name}: expected validate_plan to reject this fixture"
