"""FR-INT-09 review fixes (PR #115): bounded schema work, finite numbers, PG-10 reads a policy the
way tilo_policy does (schema, owner, history at `now`, expiry, scope, max_level), PG-06 takes the
higher of the table and connector tiers, and `skills` must be a set."""

from __future__ import annotations

import copy
import time

import pytest
from _plan_validator_lib import POL_FINANCE_UPDATES, make_gate, make_plan, make_unit, rule_ids
from tilo_planning.plangraph import validate_plan
from tilo_policy import RiskTable

NOW = "2026-10-01T00:00:00.000Z"


def _send_plan(policy_ref: str | None = "pol_finance_updates", tier: str = "T2", **plan_kwargs):
    units = [make_unit("U1", district="D2", connectors=("gmail",), actions=("send_email",))]
    return make_plan(units, [make_gate("G1", "send_email", ["U1"], tier, policy_ref)], **plan_kwargs)


def _run(plan, risk_table, connectors, skills, policies, **kwargs):
    kwargs.setdefault("now", NOW)
    return validate_plan(plan, risk_table=risk_table, connectors=connectors, skills=skills, policies=policies, **kwargs)


def _with_policy(fake_policies, **changes):
    policy = copy.deepcopy(POL_FINANCE_UPDATES)
    policy.update(changes)
    return {**fake_policies, "pol_finance_updates": policy}


# --- 1. numbers: never an OverflowError; non-finite is `schema` --------------------------------


def test_FR_INT_09_huge_int_budget_cap_is_schema(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    plan = make_plan([make_unit("U1")], [], budget_cap=10**400)
    assert rule_ids(_run(plan, risk_table, fake_connectors, fake_skills, fake_policies)) == {"schema"}


@pytest.mark.parametrize(
    ("key", "field", "value"),
    [
        pytest.param("time", "max_s", 10**400, id="huge_int_time"),
        pytest.param("credits", "max", 10**400, id="huge_int_credits"),
        pytest.param("credits", "min", float("nan"), id="nan_credits"),
        pytest.param("credits", "max", float("inf"), id="infinite_credits"),
    ],
)
def test_FR_INT_09_non_finite_number_in_any_field_is_schema(
    key, field, value, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    plan = make_plan([make_unit("U1")], [])
    plan["approaches"][0][key][field] = value
    assert rule_ids(_run(plan, risk_table, fake_connectors, fake_skills, fake_policies)) == {"schema"}


def test_FR_INT_09_too_long_number_is_schema_not_an_error(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    plan = make_plan([make_unit("U1")], [])
    plan["approaches"][0]["dimensions"]["sources"] = 10**5000  # over the maximum, too long to print
    assert rule_ids(_run(plan, risk_table, fake_connectors, fake_skills, fake_policies)) == {"schema"}


# --- 2. PG-10: a referenced policy counts only as tilo_policy would read it ---------------------


def test_FR_INT_09_PG10_owner_and_explicit_now_accept_valid_policy(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    violations = _run(_send_plan(), risk_table, fake_connectors, fake_skills, fake_policies, owner="u_owner")
    assert violations == []


def test_FR_INT_09_PG10_empty_scope_connectors_covers_nothing(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    policies = _with_policy(fake_policies, scope={"connectors": [], "recipients": [], "domains": [], "districts": []})
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies))


def test_FR_INT_09_PG10_record_failing_policy_schema_is_unusable(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    garbage = {
        "id": "pol_finance_updates",
        "action_type": "send_email",
        "level": "L3",
        "scope": {"connectors": ["gmail"], "recipients": [], "domains": [], "districts": []},
        "expiry": "zzz",
    }
    policies = {**fake_policies, "pol_finance_updates": garbage}
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies))


@pytest.mark.parametrize("scope", [None, {"connectors": "gmail"}, "gmail"], ids=["null", "partial", "str"])
def test_FR_INT_09_PG10_malformed_scope_is_unusable_not_an_error(
    scope, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    policies = _with_policy(fake_policies, scope=scope)
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies))


def test_FR_INT_09_PG10_another_owners_policy_is_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    other = copy.deepcopy(POL_FINANCE_UPDATES)
    other["owner"] = "u_other"
    other["level"] = "L3"
    other["created_by"]["by"] = "u_other"
    other["history"] = [{"by": "u_other", "at": other["created_by"]["at"], "change": "created", "level": "L3"}]
    policies = {**fake_policies, "pol_finance_updates": other}
    plan = _send_plan()
    assert "PG-10" in rule_ids(_run(plan, risk_table, fake_connectors, fake_skills, policies, owner="u_owner"))
    assert "PG-10" not in rule_ids(_run(plan, risk_table, fake_connectors, fake_skills, policies, owner="u_other"))


@pytest.mark.parametrize("record_level", ["L2", "L1"], ids=["stale_level", "consistent_level"])
def test_FR_INT_09_PG10_stop_all_in_history_is_rejected(
    record_level, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    created = POL_FINANCE_UPDATES["history"][0]
    stop_all = {"by": "u_owner", "at": "2026-09-15T00:00:00.000Z", "change": "Stop all autopilot", "level": "L1"}
    policies = _with_policy(
        fake_policies,
        level=record_level,
        changed_by={"by": "u_owner", "at": stop_all["at"]},
        history=[created, stop_all],
    )
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies))


@pytest.mark.parametrize("now", ["0", "", "2026-02-30T00:00:00.000Z", "2026-10-01T00:00:00Z"])
def test_FR_INT_09_PG10_invalid_now_fails_every_policy_gate(
    now, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    policies = _with_policy(fake_policies, expiry="2020-01-01T00:00:00.000Z")
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, fake_policies, now=now))
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies, now=now))


def test_FR_INT_09_PG10_expiry_is_read_at_now(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    policies = _with_policy(fake_policies, expiry="2026-09-20T00:00:00.000Z")
    before, after = "2026-09-10T00:00:00.000Z", "2026-09-20T00:00:00.000Z"
    assert "PG-10" not in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies, now=before))
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies, now=after))


def test_FR_INT_09_PG10_unit_connector_outside_scope_is_rejected(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    scope = {"connectors": ["web_search"], "recipients": [], "domains": [], "districts": []}
    policies = _with_policy(fake_policies, scope=scope)
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies))


def test_FR_INT_09_PG10_non_finite_limit_is_unusable(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    policies = _with_policy(fake_policies, limits={"per_day": 20, "credits": float("nan")})
    assert "PG-10" in rule_ids(_run(_send_plan(), risk_table, fake_connectors, fake_skills, policies))


def test_FR_INT_09_PG10_level_capped_by_tier_max_level(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    capped = RiskTable(
        actions=dict(risk_table.actions),
        modifiers=risk_table.modifiers,
        max_level={**risk_table.max_level, "T2": "L1"},
    )
    assert "PG-10" in rule_ids(_run(_send_plan(), capped, fake_connectors, fake_skills, fake_policies))


# --- 3. bounded schema work ---------------------------------------------------------------------


@pytest.mark.parametrize("field", ["guards", "depends_on"])
def test_FR_INT_09_oversized_array_is_schema_in_under_a_second(
    field, risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    plan = _send_plan()
    items = [{"k": i} for i in range(4000)] if field == "guards" else [i if i % 2 else str(i) for i in range(4000)]
    (plan["gates"][0] if field == "guards" else plan["units"][0])[field] = items
    started = time.perf_counter()
    violations = _run(plan, risk_table, fake_connectors, fake_skills, fake_policies)
    assert time.perf_counter() - started < 1.0
    assert rule_ids(violations) == {"schema"}


# --- 4. skills must be a set --------------------------------------------------------------------


@pytest.mark.parametrize("skills", ["table-extraction", ["table-extraction"], ("table-extraction",)])
def test_FR_INT_09_skills_must_be_a_set(skills, risk_table, fake_connectors, fake_policies) -> None:
    with pytest.raises(TypeError):
        _run(make_plan([make_unit("U1", skills=("table",))], []), risk_table, fake_connectors, skills, fake_policies)


def test_FR_INT_09_skills_frozenset_accepted(risk_table, fake_connectors, fake_skills, fake_policies) -> None:
    plan = make_plan([make_unit("U1")], [])
    assert _run(plan, risk_table, fake_connectors, frozenset(fake_skills), fake_policies) == []


# --- 5. PG-06: the higher of the risk table and the connector's declared tier -------------------


def test_FR_INT_09_PG06_connector_declared_tier_raises_the_floor(
    risk_table, fake_connectors, fake_skills, fake_policies
) -> None:
    connectors = copy.deepcopy(fake_connectors)
    for action in connectors["gmail"]["actions"]:
        if action["id"] == "send_email":
            action["risk_tier"] = "T3"  # the table still says T2
    assert "PG-06" in rule_ids(_run(_send_plan(), risk_table, connectors, fake_skills, fake_policies))
    t3 = _send_plan(policy_ref=None, tier="T3")
    assert _run(t3, risk_table, connectors, fake_skills, fake_policies) == []
