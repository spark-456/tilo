"""FR-INT-09 (PRD 7.1; contracts/plan.rules.md PG-03): "The depends_on graph has no cycles." The
deterministic-cycle example lives in `test_FR_INT_09_plan_graph_rules.py`
(`test_FR_INT_09_PG03_cycle_rejected`); this file is the invariant side of the same rule (CLAUDE.md
ticket-loop guidance: property tests for invariants such as "no cycles"): however the depends_on
edges are shuffled, as long as every unit only depends on a *strictly earlier* unit in some fixed
order, the graph is acyclic by construction, so `validate_plan` must never raise `PG-03` for it.
Uses `_plan_validator_lib`'s zero-argument registry builders directly (not the pytest fixtures in
conftest.py) because Hypothesis re-invokes the test body per example and warns about, or in some
configurations forbids, function-scoped fixtures changing across examples; the session-scoped
`risk_table`/`fake_connectors`/etc. fixtures in conftest.py exist for the ordinary (non-Hypothesis)
tests in this directory.
"""

from __future__ import annotations

from _plan_validator_lib import (
    build_fake_connectors,
    build_fake_policies,
    build_fake_skills,
    build_risk_table,
    make_plan,
    make_unit,
    rule_ids,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_planning.plangraph import validate_plan

_RISK_TABLE = build_risk_table()
_CONNECTORS = build_fake_connectors()
_SKILLS = build_fake_skills()
_POLICIES = build_fake_policies()


@st.composite
def _acyclic_units(draw):
    n = draw(st.integers(min_value=1, max_value=6))
    ids = [f"U{i + 1}" for i in range(n)]
    units = []
    for i, unit_id in enumerate(ids):
        earlier = ids[:i]
        deps = draw(st.lists(st.sampled_from(earlier), unique=True, max_size=len(earlier))) if earlier else []
        units.append(make_unit(unit_id, depends_on=deps))
    return units


@given(units=_acyclic_units())
@settings(max_examples=50, deadline=None)  # a real validator's per-call cost is unknown yet; only the outcome matters
def test_FR_INT_09_PG03_property_any_dag_of_units_is_accepted(units) -> None:
    plan = make_plan(units, [])
    violations = validate_plan(plan, risk_table=_RISK_TABLE, connectors=_CONNECTORS, skills=_SKILLS, policies=_POLICIES)
    assert "PG-03" not in rule_ids(violations), f"a depends_on DAG must never be flagged as a cycle: {units!r}"
