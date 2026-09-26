"""Budget approval (FR-INT-08, PRD 7.1, 10.4, 14.1). The person confirms a budget cap, or an autonomy policy
pre-approves it. Spending credits under the run budget is a T1 side effect (PRD 10.4), so a grant is the
`grant_budget` action run through the deterministic policy engine; no model is consulted. Only an L3 "run"
starts the work without the person: `budget.granted` then carries the policy's authz and `policy.applied`
names the policy. Every other outcome, including an engine error or a risk table without `grant_budget`,
waits for the person (the engine fails closed)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import tilo_policy

from tilo_planning.events import build_event

BUDGET_GRANT_ACTION_TYPE = "grant_budget"


@dataclass(frozen=True)
class BudgetOutcome:
    decision: tilo_policy.Decision
    granted_event: dict[str, Any] | None  # budget.granted at `seq`, only when a policy ran it
    applied_event: dict[str, Any] | None  # policy.applied at `seq + 1`, naming the policy


def _positive(cap: float) -> float:
    if isinstance(cap, bool) or not isinstance(cap, int | float) or not math.isfinite(cap) or cap <= 0:
        raise ValueError("PG-12: a budget cap is a positive number of credits")
    return cap


def _granted(cap: float, authz: dict[str, Any], actor: str, base: dict[str, Any], seq: int, how: str) -> dict:
    return build_event(
        {**base, "actor": actor}, seq=seq, type="budget.granted", target=base["world_id"], item=None,
        severity="info", tool=None, cause=None, authz=authz, data={"granted": cap, "cap": cap},
        summary=f"{cap:g} credits approved {how}; the cap is now {cap:g}.",
    )  # fmt: skip


def request_budget_grant(
    cap: float,
    *,
    table: tilo_policy.RiskTable,
    policies: list[dict[str, Any]],
    world_owner: str,
    applied: list[dict[str, Any]],
    now: str,
    base: dict[str, Any],
    seq: int,
    gate_id: str,
    outbox_id: str,
    connector: str,
    district: str,
) -> BudgetOutcome:
    """`table` is the risk-tier table to decide with; production passes one that lists `grant_budget` or
    every grant waits for the person. `applied` is the owner's policy.applied events today (daily limits)."""
    proposal = tilo_policy.Proposal(
        world_id=base["world_id"], action_type=BUDGET_GRANT_ACTION_TYPE, connector=connector, district=district,
        destination=None, facts=tilo_policy.SideEffectFacts(), item=None, credits=_positive(cap), instruction=None,
    )  # fmt: skip
    decision = tilo_policy.decide(
        proposal, table=table, policies=policies, world_owner=world_owner, applied=applied, now=now
    )
    if decision.outcome != "run" or decision.authz is None or decision.policy_id is None:
        return BudgetOutcome(decision, None, None)
    policy_id = decision.policy_id
    granted = _granted(cap, decision.authz, policy_id, base, seq, f"by policy {policy_id}")
    data = {
        "policy_id": policy_id,
        "gate_id": gate_id,
        "outbox_id": outbox_id,
        "action_type": BUDGET_GRANT_ACTION_TYPE,
        "connector": connector,
        "destination": None,
        "district": district,
        "risk_tier": decision.tier,
        "level": decision.level,
        "instruction_id": None,
        "undo_window_s": decision.undo_window_s or 0,  # L3 runs at once: no undo window
        "item": None,
        "credits": cap,
    }
    applied_event = build_event(
        {**base, "actor": policy_id}, seq=seq + 1, type="policy.applied", target=gate_id, item=None,
        severity="info", tool=None, cause=None, authz=decision.authz, data=data,
        summary=f"Policy {policy_id} approved a budget of {cap:g} credits.",
    )  # fmt: skip
    return BudgetOutcome(decision, granted, applied_event)


def grant_budget_by_person(cap: float, *, owner: str, now: str, base: dict[str, Any], seq: int) -> dict[str, Any]:
    """The person confirms the cap (FR-INT-08); `budget.granted` carries their authz."""
    authz = {"by": "person", "ref": owner, "at": now}
    return _granted(_positive(cap), authz, owner, base, seq, "by you")
