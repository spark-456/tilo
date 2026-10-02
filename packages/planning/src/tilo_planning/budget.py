"""Budget approval (FR-INT-08, PRD 7.1, 10.1, 10.4, 14.1). The world's owner confirms a budget cap, or an
autonomy policy pre-approves it. Spending credits under the run budget is a T1 side effect (PRD 10.4), so a
grant is the `grant_budget` action run through the deterministic policy engine; no model is consulted. Only
an L3 "run" starts the work without the person: `budget.granted` then carries the policy's authz, which is
the audit record naming the policy (BQ-23). A budget grant has no gate and no outbox entry, so no
`policy.applied` is built (OB-01). The policy's daily limits are counted here from the owner's earlier
policy-authorised grants. Every other outcome, including an engine error, a malformed earlier grant or a
risk table without `grant_budget`, waits for the person (fail closed). A grant is the world's first budget, so
`granted` always equals `cap`; a top-up on an existing cap is refused until Treasury applies the MT-03
ceiling (BQ-100, issue #51)."""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import tilo_policy
from tilo_contracts import EVENT_DATA_MODELS, Event

from tilo_planning.events import build_event

BUDGET_GRANT_ACTION_TYPE = "grant_budget"


class TopUpNotSupported(ValueError):
    """A grant named an existing cap; only a world's first grant is built (BQ-100)."""


@dataclass(frozen=True)
class BudgetOutcome:
    decision: tilo_policy.Decision
    granted_event: dict[str, Any] | None  # budget.granted at `seq`, only when a policy ran it


def _first_grant(existing_cap: float) -> None:
    """BQ-100: `budget.granted` records `granted == cap`, true only for a world's first grant. A top-up would
    set the cap to the increment, so any existing cap (or a value that is not a number) is refused."""
    if existing_cap != 0:  # NaN is unequal to 0, so it is refused too
        raise TopUpNotSupported("BQ-100: a top-up on an existing budget cap waits for the Treasury ticket (#51)")


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


def _day(at: str) -> str:
    return datetime.strptime(at, "%Y-%m-%dT%H:%M:%S.%fZ").strftime("%Y-%m-%d")  # anything else raises


def _over_limit(policy: dict[str, Any], earlier_grants: list[dict[str, Any]], cap: float, now: str) -> str | None:
    """PI-11 for budget grants: today's grants by this policy, this one included, within per_day and credits.
    Any malformed grant raises, and the caller waits for the person."""
    per_day, most_credits = policy["limits"]["per_day"], policy["limits"]["credits"]
    mine = []
    for grant in earlier_grants:
        Event.model_validate(grant)
        EVENT_DATA_MODELS["budget.granted"].model_validate(grant["data"])
        authz = grant["authz"]
        if grant["type"] == "budget.granted" and (authz["by"], authz["ref"]) == ("policy", policy["id"]):
            if _day(authz["at"]) == _day(now):
                mine.append(grant)
    if per_day is None or len(mine) + 1 > per_day:
        return "l3_daily_cap_reached"
    spent = [float(g["data"]["granted"]) for g in mine] + [float(cap)]
    if not all(math.isfinite(c) and c >= 0 for c in spent):
        raise ValueError("credits must be finite and non-negative")
    if most_credits is None or math.fsum(spent) > most_credits:  # no credit bound covers no cap (#106)
        return "l3_credits_cap_reached"
    return None


def request_budget_grant(
    cap: float,
    *,
    table: tilo_policy.RiskTable,
    policies: list[dict[str, Any]],
    world_owner: str,
    earlier_grants: list[dict[str, Any]],
    now: str,
    base: dict[str, Any],
    seq: int,
    connector: str,
    district: str,
    existing_cap: float = 0.0,
) -> BudgetOutcome:
    """`table` is the risk-tier table to decide with; production passes one that lists `grant_budget` or
    every grant waits for the person. `earlier_grants` is the owner's `budget.granted` events in every world
    (their daily limits). No `policy.applied` exists for a grant, so the engine is given none."""
    _first_grant(existing_cap)
    proposal = tilo_policy.Proposal(
        world_id=base["world_id"], action_type=BUDGET_GRANT_ACTION_TYPE, connector=connector, district=district,
        destination=None, facts=tilo_policy.SideEffectFacts(), item=None, credits=_positive(cap), instruction=None,
    )  # fmt: skip
    decision = tilo_policy.decide(
        proposal, table=table, policies=policies, world_owner=world_owner, applied=[], now=now
    )
    if decision.outcome != "run" or decision.authz is None or decision.policy_id is None:
        return BudgetOutcome(decision, None)
    policy_id = decision.policy_id
    try:
        policy = next(p for p in policies if isinstance(p, dict) and p.get("id") == policy_id)
        capped = _over_limit(policy, earlier_grants, cap, now)
    except Exception:  # fail closed: a grant never runs on records it cannot read
        capped = "l3_daily_cap_reached"
    if capped is not None:
        return BudgetOutcome(dataclasses.replace(decision, outcome="gate", authz=None, reason=capped), None)
    granted = _granted(cap, decision.authz, policy_id, base, seq, f"by policy {policy_id}")
    return BudgetOutcome(decision, granted)


def grant_budget_by_person(
    cap: float, *, world_owner: str, user: str, now: str, base: dict[str, Any], seq: int, existing_cap: float = 0.0
) -> dict[str, Any]:
    """The world's owner confirms the cap (FR-INT-08); only the Owner sets budgets (PRD 10.1), so an
    Approver, a Viewer or anyone else is refused. `budget.granted` carries the owner's authz."""
    if not world_owner or user != world_owner:
        raise PermissionError("PRD 10.1: only the world's owner sets budgets")
    _first_grant(existing_cap)
    authz = {"by": "person", "ref": user, "at": now}
    return _granted(_positive(cap), authz, user, base, seq, "by you")
