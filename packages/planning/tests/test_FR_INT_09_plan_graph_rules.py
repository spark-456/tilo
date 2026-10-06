"""FR-INT-09 (PRD 7.1; contracts/plan.rules.md PG-01..PG-11): one test per cross-reference rule
that plan.schema.json cannot express on its own (PG-12 is schema-level and is covered by
`test_FR_INT_09_plan_schema_fixtures.py` instead -- see that file's docstring).

Each test builds the smallest PlanGraph that isolates its rule: everything else about the plan is
kept deliberately boring (a `specialist` unit in `D1` with the `table-extraction` skill and no
connectors/actions, from `_plan_validator_lib.make_unit`'s defaults) so a failure can only be the
rule under test, not a side effect of some other rule. `_plan_validator_lib.rule_ids` reads the
`.rule_id` off every returned `Violation` (this ticket's own interface design -- see that module's
docstring) so tests assert membership (`"PG-04" in rule_ids(...)`) rather than exact equality,
since a deliberately-broken plan may trip more than one rule.
"""

from __future__ import annotations

import copy

import pytest
from _plan_validator_lib import approaches_2, make_gate, make_plan, make_unit, rule_ids
from tilo_planning.plangraph import validate_plan


def _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies):
    return validate_plan(
        plan, risk_table=risk_table, connectors=fake_connectors, skills=fake_skills, policies=fake_policies
    )


# --- PG-01: unit ids unique within the plan; gate ids unique within the plan -------------------


def test_FR_INT_09_PG01_duplicate_unit_id_rejected(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    plan = make_plan([make_unit("U1"), make_unit("U1")], [])
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-01" in rule_ids(violations)


def test_FR_INT_09_PG01_duplicate_gate_id_rejected(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    units = [
        make_unit("U1", district="D2", connectors=("gmail",), actions=("send_email",)),
        make_unit("U2", district="D2", connectors=("gmail",), actions=("send_email",)),
    ]
    gates = [
        make_gate("G1", "send_email", ["U1"], "T2", "pol_finance_updates"),
        make_gate("G1", "send_email", ["U2"], "T2", "pol_finance_updates"),
    ]
    plan = make_plan(units, gates)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-01" in rule_ids(violations)


# --- PG-02: every depends_on id names a unit in the same plan; no unit depends on itself -------


@pytest.mark.parametrize(
    "depends_on",
    [pytest.param(["U99"], id="unknown_unit"), pytest.param(["U1"], id="self_dependency")],
)
def test_FR_INT_09_PG02_bad_dependency_rejected(
    depends_on, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    plan = make_plan([make_unit("U1", depends_on=depends_on)], [])
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-02" in rule_ids(violations)


# --- PG-03: the depends_on graph has no cycles --------------------------------------------------


def test_FR_INT_09_PG03_cycle_rejected(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    units = [make_unit("U1", depends_on=["U2"]), make_unit("U2", depends_on=["U1"])]
    plan = make_plan(units, [])
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-03" in rule_ids(violations)


# --- PG-04: every irreversible action maps to a gate. "A plan with an email send fails --------
# --- validation unless a gate guards it" (plan.rules.md, quoting FR-INT-09's own example) ------


def test_FR_INT_09_PG04_unguarded_email_send_rejected(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    from _plan_validator_lib import load_plan_fixture  # noqa: PLC0415

    guarded = load_plan_fixture("valid", "two_approaches_email_send_gated")
    unguarded = copy.deepcopy(guarded)
    unguarded["gates"] = []

    guarded_violations = _validate(guarded, risk_table, fake_connectors, fake_skills, fake_policies)
    unguarded_violations = _validate(unguarded, risk_table, fake_connectors, fake_skills, fake_policies)

    assert guarded_violations == [], f"expected the gated plan to be valid, got {rule_ids(guarded_violations)}"
    assert "PG-04" in rule_ids(unguarded_violations)


# --- PG-05: a gate guards only units that list its action_type in their own actions ------------


def test_FR_INT_09_PG05_gate_guards_unit_missing_the_action_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    units = [
        make_unit("U1", district="D2", connectors=("gmail",), actions=("send_email",)),
        make_unit("U2"),  # no actions at all
    ]
    gates = [make_gate("G1", "send_email", ["U1", "U2"], "T2", "pol_finance_updates")]
    plan = make_plan(units, gates)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-05" in rule_ids(violations)


# --- PG-06: a gate's risk_tier is never lower than config/autonomy.yaml's tier for its action --


def test_FR_INT_09_PG06_gate_tier_below_config_base_tier_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    # send_email's base tier in config/autonomy.yaml is T2; a T1 gate is a rule break.
    units = [make_unit("U1", district="D2", connectors=("gmail",), actions=("send_email",))]
    gates = [make_gate("G1", "send_email", ["U1"], "T1", None)]
    plan = make_plan(units, gates)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-06" in rule_ids(violations)


# --- PG-07: chosen_approach names one of approaches[].id; approach ids are unique --------------


def test_FR_INT_09_PG07_chosen_approach_not_in_approaches_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    plan = make_plan([make_unit("U1")], [], chosen="does_not_exist")
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-07" in rule_ids(violations)


def test_FR_INT_09_PG07_duplicate_approach_ids_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    approaches = approaches_2()
    approaches[1]["id"] = approaches[0]["id"]  # both "quick" now
    plan = make_plan([make_unit("U1")], [], approaches=approaches, chosen=approaches[0]["id"])
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-07" in rule_ids(violations)


# --- PG-08: every pair of approaches differs on at least 2 of the 5 dimensions -----------------


def test_FR_INT_09_PG08_approaches_differ_on_only_one_dimension_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    approaches = approaches_2()
    # Make approach 2 identical to approach 1 except for one dimension (sources).
    approaches[1]["dimensions"] = dict(approaches[0]["dimensions"])
    approaches[1]["dimensions"]["sources"] = approaches[0]["dimensions"]["sources"] + 1
    plan = make_plan([make_unit("U1")], [], approaches=approaches)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-08" in rule_ids(violations)


# --- PG-09: time.min_s <= time.max_s and credits.min <= credits.max ----------------------------


@pytest.mark.parametrize(
    "field,broken",
    [
        pytest.param("time", {"min_s": 500, "max_s": 100}, id="time_reversed"),
        pytest.param("credits", {"min": 100, "max": 10}, id="credits_reversed"),
    ],
)
def test_FR_INT_09_PG09_reversed_range_rejected(
    field, broken, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    approaches = approaches_2()
    approaches[0][field] = broken
    plan = make_plan([make_unit("U1")], [], approaches=approaches)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-09" in rule_ids(violations)


# --- PG-10: a non-null policy_ref names an existing, unexpired L2/L3 policy for the same -------
# --- action type whose scope covers the guarded units' connectors and districts ----------------


@pytest.mark.parametrize(
    "policy_ref",
    [
        pytest.param("pol_does_not_exist", id="unknown_policy"),
        pytest.param("pol_drive_saves", id="wrong_action_type"),  # save_file, not send_email
        pytest.param("pol_finance_updates_expired", id="expired"),
        pytest.param("pol_finance_updates_l1", id="wrong_level"),
        pytest.param("pol_finance_updates_wrong_scope", id="scope_does_not_cover_connector"),
    ],
)
def test_FR_INT_09_PG10_bad_policy_ref_rejected(
    policy_ref, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    units = [make_unit("U1", district="D2", connectors=("gmail",), actions=("send_email",))]
    gates = [make_gate("G1", "send_email", ["U1"], "T2", policy_ref)]
    plan = make_plan(units, gates)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-10" in rule_ids(violations)


def test_FR_INT_09_PG10_valid_policy_ref_accepted(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    units = [make_unit("U1", district="D2", connectors=("gmail",), actions=("send_email",))]
    gates = [make_gate("G1", "send_email", ["U1"], "T2", "pol_finance_updates")]
    plan = make_plan(units, gates)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-10" not in rule_ids(violations)


# --- PG-11: skill/connector ids resolve; every action type in a unit's actions is declared by --
# --- one of that unit's connectors with gate_type: approval -------------------------------------


def test_FR_INT_09_PG11_unknown_skill_id_rejected(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    plan = make_plan([make_unit("U1", skills=("not-a-real-skill",))], [])
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-11" in rule_ids(violations)


def test_FR_INT_09_PG11_unknown_connector_id_rejected(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    plan = make_plan([make_unit("U1", connectors=("not_a_real_connector",))], [])
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-11" in rule_ids(violations)


def test_FR_INT_09_PG11_action_not_declared_by_any_connector_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    # gmail declares no "delete_file" action at all.
    units = [make_unit("U1", district="D2", connectors=("gmail",), actions=("delete_file",))]
    gates = [make_gate("G1", "delete_file", ["U1"], "T3", None)]
    plan = make_plan(units, gates)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-11" in rule_ids(violations)


def test_FR_INT_09_PG11_read_only_action_used_as_side_effect_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    # gmail declares "search_email" with gate_type: none (read-only) -- listing it as a side
    # effect the plan gates is a PG-11 break, not a legitimate T3 escalation.
    units = [make_unit("U1", district="D2", connectors=("gmail",), actions=("search_email",))]
    gates = [make_gate("G1", "search_email", ["U1"], "T3", None)]
    plan = make_plan(units, gates)
    violations = _validate(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert "PG-11" in rule_ids(violations)
