"""tilo_policy.decide — gate, draft only, run after undo, or run (PRD 10.4; PI-06..PI-13).
Deterministic: `now` is the only time source and no model is consulted. T3 always gates, and so
does no covering policy or any error on the way (fail closed)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .coverage import Target, applied_ok, covering_level, fail_closed, instruction_counts, ts
from .tiers import RiskTable, SideEffectFacts


@dataclass(frozen=True)
class Proposal:
    world_id: str
    action_type: str
    connector: str
    district: str
    destination: str | None
    facts: SideEffectFacts
    item: dict | None
    credits: float
    instruction: dict | None


@dataclass(frozen=True)
class Decision:
    outcome: str
    tier: str
    modifiers: tuple[str, ...]
    level: str
    policy_id: str | None
    authz: dict | None
    undo_window_s: int | None
    scheduled_at: str | None
    reason: str


def gate(tier: str, modifiers: tuple[str, ...], level: str, policy_id: str | None, reason: str) -> Decision:
    """A gate authorises nothing (PI-01): no authz, no schedule."""
    return Decision("gate", tier, modifiers, level, policy_id, None, None, None, reason)


@fail_closed("l3_daily_cap_reached")
def over_limit(policy: dict, applied: list[dict], credits: float, now: str) -> str | None:
    """PI-11: today's actions under this policy, this one included, within per_day and credits.
    `applied` holds the owner's policy.applied parts in every world, so caps never multiply."""
    if not applied_ok(applied):
        raise ValueError("malformed policy.applied part")
    per_day, most_credits = policy["limits"]["per_day"], policy["limits"]["credits"]
    day = ts(now)[:10]
    mine = [a for a in applied if a["data"]["policy_id"] == policy["id"] and ts(a["authz"]["at"])[:10] == day]
    if per_day is None or len(mine) + 1 > per_day:  # L2 and L3 always have a daily limit (schema)
        return "l3_daily_cap_reached"
    if most_credits is None:
        return None
    spent = [float(a["credits"]) for a in mine] + [float(credits)]
    if any(not c >= 0 for c in spent):  # negative or NaN credits never lower the total
        raise ValueError("credits must be non-negative")
    return "l3_credits_cap_reached" if math.fsum(spent) > most_credits else None


def decide(
    proposal: Proposal, *, table: RiskTable, policies: list[dict], world_owner: str, applied: list[dict], now: str
) -> Decision:
    try:
        return _decide(proposal, table, policies, world_owner, applied, ts(now))
    except Exception:  # fail closed: nothing unexpected ever runs
        return gate("T3", (), "L1", None, "no_covering_policy")


def _decide(p: Proposal, table: RiskTable, policies: list[dict], owner: str, applied: list[dict], now: str) -> Decision:
    tier, modifiers = (a := table.assess(p.action_type, p.facts)).tier, a.modifiers
    if tier == "T3":
        return gate(tier, modifiers, "L1", None, "t3_always_gates")
    target = Target(p.action_type, p.connector, p.district, p.facts.recipients)
    levels = [(lv, pol) for pol in policies if (lv := covering_level(pol, target, owner, now))]
    # A tier's max_level caps every policy; the lowest level in force wins, ties by id (PI-13).
    covering = [(min(lv, table.max_level.get(tier, "L1")), pol["id"], pol) for lv, pol in levels]
    if not covering:
        return gate(tier, modifiers, "L1", None, "no_covering_policy")
    level, policy_id, policy = min(covering, key=lambda c: (c[0], c[1]))
    if level == "L0":
        return Decision("draft_only", tier, modifiers, level, policy_id, None, None, None, "l0_draft_only")
    if level == "L1":
        return gate(tier, modifiers, level, policy_id, "no_covering_policy")
    window = policy["undo_window_s"]
    if level == "L2" and not (  # PI-12: an L2 send never loses its undo window
        isinstance(window, int)
        and window >= 1
        and instruction_counts(p.instruction, p.world_id, owner, p.destination, now, applied)
    ):
        return gate(tier, modifiers, level, policy_id, "l2_instruction_required")
    capped = over_limit(policy, applied, p.credits, now)
    if capped is not None:
        return gate(tier, modifiers, level, policy_id, capped)
    authz = {"by": "policy", "ref": policy_id, "at": now}
    if level == "L3":
        return Decision("run", tier, modifiers, level, policy_id, authz, None, None, "l3_run")
    moved = datetime.strptime(now, "%Y-%m-%dT%H:%M:%S.%fZ") + timedelta(seconds=window)
    at = moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"
    return Decision("run_after_undo", tier, modifiers, level, policy_id, authz, window, at, "l2_run_after_undo")
