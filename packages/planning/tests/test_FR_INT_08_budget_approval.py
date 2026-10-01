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
prd_10_4_tiers.json`'s shape exactly. The policy proposal's `connector` (matched against a
policy's `scope.connectors`) has no natural value for a non-connector side effect like a budget
grant; a placeholder id, `internal`, is used (schema-valid, not in `config/connectors.yaml`) --
an application ambiguity, not a contract gap.

Design: `request_budget_grant` runs `tilo_policy.decide` for a `cap`-credit `grant_budget`
proposal. Outcome "run" (a covering L3 policy within its daily limits, PI-11) builds one
`budget.granted` whose authz is `{by: policy, ref: <policy id>}` (BQ-23): that is the audit
record naming the policy. No gate and no outbox entry exist for a budget grant, so no
`policy.applied` is built and no gate or outbox id is invented (review round 1, OB-01). The
policy's per_day and credits limits are counted from the owner's earlier policy-authorised
`budget.granted` events on the same UTC day. Any other outcome (no covering policy, over limit,
T3, ...) returns no event: FR-INT-08 "waits for the person", and only the world's owner may then
confirm through `grant_budget_by_person` (PRD 10.1: only the Owner sets budgets).

Public interface: `tilo_planning.budget.request_budget_grant`, `.grant_budget_by_person`,
`.BudgetOutcome`, `.BUDGET_GRANT_ACTION_TYPE`.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib
from typing import Any

import pytest
import tilo_policy
import yaml
from _planning_contracts_lib import (
    assert_valid_event,
    base_budget_policy,
    budget_grant_risk_table_path,
    sample_event_base,
)
from tilo_planning.budget import grant_budget_by_person, request_budget_grant

OWNER = "u_owner"
NOW = "2026-09-29T09:42:16.000Z"
SINCE = "2026-09-28T00:00:00.000Z"  # a policy in force before every earlier grant below
CONNECTOR = "internal"
DISTRICT = "D1"


def _table():
    return tilo_policy.load_risk_table(budget_grant_risk_table_path())


def _grant(cap: float, *, policies: list[dict], earlier_grants: list[dict] | None = None, now: str = NOW):
    return request_budget_grant(
        cap,
        table=_table(),
        policies=policies,
        world_owner=OWNER,
        earlier_grants=earlier_grants or [],
        now=now,
        base=sample_event_base(),
        seq=2,
        connector=CONNECTOR,
        district=DISTRICT,
    )


def _emitted(outcome: Any) -> list[dict]:
    """Every event the outcome carries, whatever its field names."""
    values = [getattr(outcome, f.name) for f in dataclasses.fields(outcome)]
    return [v for v in values if isinstance(v, dict) and "type" in v]


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def test_FR_INT_08_policy_auto_approves_an_80_credit_approach_under_a_100_credit_threshold(repo_root, registry):
    policy = base_budget_policy(credits=100)

    outcome = _grant(80, policies=[policy])

    assert outcome.decision.outcome == "run", "80 credits is under the 100-credit auto-approve threshold"
    assert outcome.granted_event is not None, "FR-INT-08: it starts -- budget.granted is emitted"
    assert outcome.granted_event["type"] == "budget.granted"
    # FR-INT-08: "the audit log names the policy" -- the grant's authz is the policy (BQ-23).
    assert outcome.granted_event["authz"] == {"by": "policy", "ref": policy["id"], "at": NOW}
    assert outcome.granted_event["actor"] == policy["id"]
    assert policy["id"] in outcome.granted_event["summary"]
    assert outcome.granted_event["data"]["granted"] == 80
    assert outcome.granted_event["data"]["cap"] == 80
    assert_valid_event(repo_root, registry, outcome.granted_event)


def test_FR_INT_08_every_emitted_event_is_schema_valid_registered_and_carries_no_gate_or_outbox_id(repo_root, registry):
    """Review round 1 (OB-01): no gate and no outbox entry exist for a budget grant, so nothing
    emitted may name one, and no policy.applied is built without them."""
    types = yaml.safe_load((repo_root / "contracts" / "events" / "registry.yaml").read_text(encoding="utf-8"))["types"]
    outcome = _grant(80, policies=[base_budget_policy(credits=100)])

    emitted = _emitted(outcome)
    assert [e["type"] for e in emitted] == ["budget.granted"]
    for event in emitted:
        assert event["type"] in types, f"{event['type']} is not registered"
        entry = types[event["type"]]
        if entry["side_effect"]:
            assert event["authz"]["by"] in entry["authz_by"]
        assert_valid_event(repo_root, registry, event)
        assert not {"gate_id", "outbox_id"} & _keys(event), "no invented gate or outbox id"
        assert event["target"] == event["world_id"]


def test_FR_INT_08_a_120_credit_approach_does_not_auto_start_it_waits_for_the_owner(repo_root, registry):
    policy = base_budget_policy(credits=100)

    outcome = _grant(120, policies=[policy])

    assert outcome.decision.outcome != "run", "120 credits is over the 100-credit auto-approve threshold"
    assert _emitted(outcome) == [], "FR-INT-08: it must not start automatically"

    # The owner confirms it directly instead (FR-INT-08: "the user picks an approach and confirms a budget cap").
    person_event = grant_budget_by_person(
        120, world_owner=OWNER, user=OWNER, now=NOW, base=sample_event_base(), seq=2
    )  # fmt: skip
    assert person_event["type"] == "budget.granted"
    assert person_event["authz"] == {"by": "person", "ref": OWNER, "at": NOW}
    assert person_event["data"] == {"granted": 120, "cap": 120}
    assert_valid_event(repo_root, registry, person_event)


@pytest.mark.parametrize("user", ["u_approver", "u_viewer", "u_stranger"])
def test_FR_INT_08_only_the_world_owner_may_grant_a_budget(user: str):
    """PRD 10.1: only the Owner sets budgets; an Approver, a Viewer or a stranger is refused."""
    with pytest.raises(PermissionError):
        grant_budget_by_person(120, world_owner=OWNER, user=user, now=NOW, base=sample_event_base(), seq=2)


def test_FR_INT_08_no_covering_policy_waits_for_the_person():
    outcome = _grant(10, policies=[])  # no autonomy policy at all

    assert outcome.decision.outcome != "run"
    assert _emitted(outcome) == []


def _earlier(granted: float, *, by: str = "policy", ref: str = "pol_auto_budget_100", at: str = NOW) -> dict:
    """An earlier budget.granted event, authorised by `ref` (a policy id or a person)."""
    if by == "person":
        return grant_budget_by_person(granted, world_owner=ref, user=ref, now=at, base=sample_event_base(), seq=1)
    outcome = request_budget_grant(
        granted, table=_table(), policies=[base_budget_policy(id_=ref, per_day=50, credits=None, created_at=SINCE)],
        world_owner=OWNER, earlier_grants=[], now=at, base=sample_event_base(), seq=1,
        connector=CONNECTOR, district=DISTRICT,
    )  # fmt: skip
    assert outcome.granted_event is not None
    return outcome.granted_event


def test_FR_INT_08_per_day_limit_counts_earlier_policy_authorised_grants():
    policy = base_budget_policy(per_day=2, credits=None)
    earlier = [_earlier(5, at="2026-09-29T08:00:00.000Z"), _earlier(5, at="2026-09-29T09:00:00.000Z")]

    outcome = _grant(5, policies=[policy], earlier_grants=earlier)

    assert outcome.decision.outcome == "gate"
    assert outcome.decision.authz is None
    assert outcome.granted_event is None
    assert _grant(5, policies=[policy], earlier_grants=earlier[:1]).decision.outcome == "run"


def test_FR_INT_08_credits_limit_counts_earlier_policy_authorised_grants():
    policy = base_budget_policy(credits=100)
    earlier = [_earlier(60, at="2026-09-29T08:00:00.000Z")]

    assert _grant(50, policies=[policy], earlier_grants=earlier).granted_event is None, "60 + 50 > 100"
    assert _grant(40, policies=[policy], earlier_grants=earlier).granted_event is not None, "60 + 40 <= 100"


def test_FR_INT_08_limits_ignore_person_grants_other_policies_and_other_days():
    policy = base_budget_policy(per_day=1, credits=100)
    earlier = [
        _earlier(90, by="person", ref=OWNER),
        _earlier(90, ref="pol_other"),
        _earlier(90, at="2026-09-28T23:59:59.999Z"),
    ]

    assert _grant(80, policies=[policy], earlier_grants=earlier).granted_event is not None


def test_FR_INT_08_a_malformed_earlier_grant_fails_closed():
    policy = base_budget_policy(credits=100)
    bad = _earlier(10, at="2026-09-29T08:00:00.000Z")
    bad["data"]["granted"] = -50  # would lower the day's total

    assert _grant(10, policies=[policy], earlier_grants=[bad]).granted_event is None


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
