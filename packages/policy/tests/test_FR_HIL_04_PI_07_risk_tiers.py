"""FR-HIL-04 / PI-07 (docs/security/p4-policy-invariants.md): risk tiers are assigned
deterministically by action type and context (PRD 10.4); any of the six T3 modifiers raises the
action to T3 whatever its base tier, and an unknown action type is fail-closed T3.

load_risk_table (API.md) reads and validates contracts/policy.schema.json#/$defs/risk_tier_table
fail-closed: config/autonomy.yaml is not in the repo yet (spark-456/tilo#1, conftest.py
risk_table_path), so every test here loads an explicit fixture path instead of the default.
"""

from __future__ import annotations

import pytest
import tilo_policy
from conftest import base_facts


def test_FR_HIL_04_PI_07_valid_risk_table_loads(risk_table_path):
    table = tilo_policy.load_risk_table(risk_table_path)
    assert table.actions["send_email"] == "T2"
    assert table.actions["create_draft"] == "T1"
    assert table.actions["share_file"] == "T3"
    assert set(table.modifiers) == {
        "new_recipients",
        "attachments",
        "external_sharing",
        "deletion",
        "money_or_legal",
        "safety_flag",
    }
    assert table.max_level == {"T1": "L3", "T2": "L3", "T3": "L1"}


def test_FR_HIL_04_PI_07_missing_risk_table_file_raises(tmp_path):
    with pytest.raises(tilo_policy.PolicyConfigError):
        tilo_policy.load_risk_table(tmp_path / "does_not_exist.yaml")


def test_FR_HIL_04_PI_07_every_invalid_risk_table_fixture_raises(risk_table_invalid_paths):
    assert risk_table_invalid_paths, "contracts/fixtures/policy.risk_tier_table/invalid/ must hold fixtures"
    for path in risk_table_invalid_paths:
        with pytest.raises(tilo_policy.PolicyConfigError):
            tilo_policy.load_risk_table(path)


@pytest.mark.parametrize(
    "action_type,facts_overrides,expected_tier",
    [
        ("create_draft", {}, "T1"),
        ("save_file", {}, "T1"),
        ("send_email", {}, "T2"),
        ("post_status_update", {}, "T2"),
        ("share_file", {}, "T3"),
        ("delete_file", {}, "T3"),
    ],
)
def test_FR_HIL_04_PI_07_base_tier_with_no_modifiers(risk_table_path, action_type, facts_overrides, expected_tier):
    table = tilo_policy.load_risk_table(risk_table_path)
    facts = tilo_policy.SideEffectFacts(**base_facts(**facts_overrides))
    assessment = table.assess(action_type, facts)
    assert assessment.tier == expected_tier
    assert assessment.modifiers == ()


@pytest.mark.parametrize(
    "facts_overrides,expected_modifier",
    [
        ({"recipients": ("new@example.com",), "known_recipients": ("riya@example.com",)}, "new_recipients"),
        ({"attachments": ({"artifact_id": "art_x", "version": 1},)}, "attachments"),
        ({"external_share": True}, "external_sharing"),
        ({"deletion": True}, "deletion"),
        ({"money_or_legal": True}, "money_or_legal"),
        ({"safety_flags": True}, "safety_flag"),
    ],
)
def test_FR_HIL_04_PI_07_any_modifier_forces_T3(risk_table_path, facts_overrides, expected_modifier):
    """PI-07: any of the six modifiers makes the action T3, whatever its base tier — here a base
    T1 action_type (create_draft, PRD 10.4 table) that would otherwise stay at L3."""
    table = tilo_policy.load_risk_table(risk_table_path)
    facts = tilo_policy.SideEffectFacts(**base_facts(**facts_overrides))
    assessment = table.assess("create_draft", facts)
    assert assessment.tier == "T3"
    assert expected_modifier in assessment.modifiers


def test_FR_HIL_04_PI_07_unknown_action_type_is_fail_closed_T3(risk_table_path):
    table = tilo_policy.load_risk_table(risk_table_path)
    facts = tilo_policy.SideEffectFacts(**base_facts())
    assessment = table.assess("an_action_type_nobody_registered", facts)
    assert assessment.tier == "T3"


def test_FR_HIL_04_PI_07_new_recipients_is_recipients_minus_known(risk_table_path):
    facts = tilo_policy.SideEffectFacts(
        **base_facts(recipients=("riya@example.com", "new@example.com"), known_recipients=("riya@example.com",))
    )
    assert facts.new_recipients == ("new@example.com",)


def test_FR_HIL_04_PI_07_no_new_recipients_when_all_known(risk_table_path):
    facts = tilo_policy.SideEffectFacts(**base_facts())
    assert facts.new_recipients == ()
