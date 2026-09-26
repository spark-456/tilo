"""FR-INT-08 (PRD 7.1): "The user picks an approach and confirms a budget cap; an autonomy
policy may pre-approve budgets under a threshold." Acceptance test: "Given a policy of
'auto-approve under 100 credits', when an approach costs 80, then it starts and the audit log
names the policy." PRD 10.4: "the engine is deterministic code; a model never decides whether
something is authorised" -- WHO authorised the grant (BQ-23: `budget.granted` authz is person or
policy) comes only from `tilo_policy.decide` (packages/policy, read-only context for this
ticket), never a model.

Ambiguity resolved here (CLAUDE.md: PRD's stated default): PRD 10.4's own T1 risk-tier example is
literally "spend credits under the run budget", so a budget grant is modelled as one T1 action
type, `grant_budget`, run through the same `tilo_policy.decide` path as any other side effect.
`config/autonomy.yaml` (read-only context) does not define this action type yet -- **needs
contract/config change**: add a `grant_budget` entry to `config/autonomy.yaml`'s risk-tier table
(reported in the test-writer summary, not made here). Until then these tests load a package-local
risk table fixture (`fixtures/policy/budget_grant_risk_table.json`) with the same six PRD 10.4
modifiers plus this one action at T1, mirroring `contracts/fixtures/policy.risk_tier_table/valid/
prd_10_4_tiers.json`'s shape exactly. The `policy.applied` event's `connector` field (required by
`contracts/events/data/policy.applied.schema.json`) has no natural value for a non-connector side
effect like a budget grant; the nearest existing field is used with a placeholder id, `internal`
(schema-valid, not in `config/connectors.yaml`) -- an application ambiguity, not a contract gap.

Design (this ticket -- `tilo_planning.budget` does not exist yet): `request_budget_grant` runs
`tilo_policy.decide` for a `cap`-credit `grant_budget` proposal. Outcome "run" (a covering L3
policy within its daily limits, PI-11) builds `budget.granted` (authz by policy) and
`policy.applied` (naming the policy, BQ-23/OB-01) at `seq`/`seq + 1`. Any other outcome (no
covering policy, over limit, T3, ...) returns no events: FR-INT-08 "waits for the person", who
then confirms directly through `grant_budget_by_person`.

Public interface: `tilo_planning.budget.request_budget_grant`, `.grant_budget_by_person`,
`.BudgetOutcome`, `.BUDGET_GRANT_ACTION_TYPE`.
"""

from __future__ import annotations

import ast
import pathlib

import tilo_policy
from _planning_contracts_lib import (
    assert_valid_event,
    base_budget_policy,
    budget_grant_risk_table_path,
    sample_event_base,
)
from tilo_planning.budget import grant_budget_by_person, request_budget_grant

OWNER = "u_owner"
NOW = "2026-09-29T09:42:16.000Z"
GATE_ID = "G1"
OUTBOX_ID = "01JB5VQ0000000000000009002"
CONNECTOR = "internal"
DISTRICT = "D1"


def _table():
    return tilo_policy.load_risk_table(budget_grant_risk_table_path())


def _grant(cap: float, *, policies: list[dict]):
    return request_budget_grant(
        cap,
        table=_table(),
        policies=policies,
        world_owner=OWNER,
        applied=[],
        now=NOW,
        base=sample_event_base(),
        seq=2,
        gate_id=GATE_ID,
        outbox_id=OUTBOX_ID,
        connector=CONNECTOR,
        district=DISTRICT,
    )


def test_FR_INT_08_policy_auto_approves_an_80_credit_approach_under_a_100_credit_threshold(repo_root, registry):
    policy = base_budget_policy(credits=100)

    outcome = _grant(80, policies=[policy])

    assert outcome.decision.outcome == "run", "80 credits is under the 100-credit auto-approve threshold"
    assert outcome.granted_event is not None, "FR-INT-08: it starts -- budget.granted is emitted"
    assert outcome.granted_event["type"] == "budget.granted"
    assert outcome.granted_event["authz"] == {"by": "policy", "ref": policy["id"], "at": NOW}
    assert outcome.granted_event["data"]["granted"] == 80
    assert outcome.granted_event["data"]["cap"] == 80
    assert_valid_event(repo_root, registry, outcome.granted_event)

    assert outcome.applied_event is not None, "FR-INT-08: 'the audit log names the policy'"
    assert outcome.applied_event["type"] == "policy.applied"
    assert outcome.applied_event["data"]["policy_id"] == policy["id"]
    assert outcome.applied_event["data"]["credits"] == 80
    assert_valid_event(repo_root, registry, outcome.applied_event)


def test_FR_INT_08_a_120_credit_approach_does_not_auto_start_it_waits_for_the_person(repo_root, registry):
    policy = base_budget_policy(credits=100)

    outcome = _grant(120, policies=[policy])

    assert outcome.decision.outcome != "run", "120 credits is over the 100-credit auto-approve threshold"
    assert outcome.granted_event is None, "FR-INT-08: it must not start automatically"
    assert outcome.applied_event is None

    # The person confirms it directly instead (FR-INT-08: "the user picks an approach and confirms a budget cap").
    person_event = grant_budget_by_person(120, owner=OWNER, now=NOW, base=sample_event_base(), seq=2)
    assert person_event["type"] == "budget.granted"
    assert person_event["authz"] == {"by": "person", "ref": OWNER, "at": NOW}
    assert person_event["data"] == {"granted": 120, "cap": 120}
    assert_valid_event(repo_root, registry, person_event)


def test_FR_INT_08_no_covering_policy_waits_for_the_person():
    outcome = _grant(10, policies=[])  # no autonomy policy at all

    assert outcome.decision.outcome != "run"
    assert outcome.granted_event is None
    assert outcome.applied_event is None


def test_FR_INT_08_authorisation_decision_never_imports_a_model_provider(repo_root: pathlib.Path):
    """PRD 10.4: "the engine is deterministic code; a model never decides whether something is
    authorised" -- tilo_planning.budget must delegate to tilo_policy.decide, never call a model."""
    path = repo_root / "packages" / "planning" / "src" / "tilo_planning" / "budget.py"
    assert path.is_file(), "tilo_planning/budget.py must exist once FR-INT-08 is implemented"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    assert "tilo_providers" not in found, "a model never decides budget authorisation (PRD 10.4)"
    assert "tilo_policy" in found, "the decision must come from the deterministic policy engine"
