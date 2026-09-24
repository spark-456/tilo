"""PRD 10.4 Autonomy policies (ticket P0-02 section 1 policy.schema.json and
common.schema.json).

Ticket's rule test: "policy level is one of L0-L3 and risk tier one of
T1-T3." `common.schema.json` is where the ticket puts the shared `risk_tier`
(T1 T2 T3) and `autonomy_level` (L0 L1 L2 L3) `$defs`, referenced by
`policy.schema.json`'s `level` field (PRD 10.4 "Policy object": "... level,
undo window, ...") and by the risk-tier table's tier values.
"""

from __future__ import annotations

import copy

import pytest
from _lib import SCHEMA_ID_TEMPLATE, errors_for, list_fixtures, load_json, load_schema

COMMON_ID = SCHEMA_ID_TEMPLATE.format(name="common")


def _def_ref_schema(def_name: str) -> dict:
    return {"$ref": f"{COMMON_ID}#/$defs/{def_name}"}


@pytest.mark.parametrize("value", ["L0", "L1", "L2", "L3"])
def test_PRD_10_4_common_autonomy_level_accepts_l0_to_l3(repo_root, registry, value):
    load_schema(repo_root, "common")  # asserts contracts/common.schema.json exists
    schema = _def_ref_schema("autonomy_level")
    errors = errors_for(schema, value, registry)
    assert not errors, f"PRD 10.4: common $defs.autonomy_level must accept {value!r}"


def test_PRD_10_4_common_autonomy_level_rejects_l4(repo_root, registry):
    load_schema(repo_root, "common")
    schema = _def_ref_schema("autonomy_level")
    errors = errors_for(schema, "L4", registry)
    assert errors, "PRD 10.4: common $defs.autonomy_level must reject 'L4' (only L0-L3 exist)"


@pytest.mark.parametrize("value", ["T1", "T2", "T3"])
def test_PRD_10_4_common_risk_tier_accepts_t1_to_t3(repo_root, registry, value):
    load_schema(repo_root, "common")
    schema = _def_ref_schema("risk_tier")
    errors = errors_for(schema, value, registry)
    assert not errors, f"PRD 10.4: common $defs.risk_tier must accept {value!r}"


def test_PRD_10_4_common_risk_tier_rejects_t4(repo_root, registry):
    load_schema(repo_root, "common")
    schema = _def_ref_schema("risk_tier")
    errors = errors_for(schema, "T4", registry)
    assert errors, "PRD 10.4: common $defs.risk_tier must reject 'T4' (only T1-T3 exist)"


@pytest.fixture()
def a_valid_policy(repo_root):
    fixtures = list_fixtures(repo_root, "policy", "valid")
    assert fixtures, "PRD 10.4: need at least one contracts/fixtures/policy/valid/*.json to mutate"
    instance = load_json(fixtures[0])
    assert "level" in instance, f"PRD 10.4: the valid policy fixture {fixtures[0].name} must have a 'level' field"
    return instance


def test_PRD_10_4_policy_with_invalid_level_is_invalid(repo_root, registry, a_valid_policy):
    schema = load_schema(repo_root, "policy")
    mutated = copy.deepcopy(a_valid_policy)
    mutated["level"] = "L4"
    errors = errors_for(schema, mutated, registry)
    assert errors, "PRD 10.4: a policy with level 'L4' must be invalid against policy.schema.json"
