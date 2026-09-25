"""tilo_policy.gate — opening a gate (PRD 10.1, 10.3; PI-02..PI-04, SEC-06). Only approve on this
gate from someone allowed to open it opens it; the authz is theirs, never a policy's or the
Director's."""

from __future__ import annotations

from .coverage import opens_gate
from .decide import Decision, gate


def open_gate(
    reserved: dict,
    resolved: dict | None,
    *,
    world_owner: str,
    team_lead: dict | None = None,
    policy: dict | None = None,
) -> Decision:
    try:
        tier = reserved["data"]["risk_tier"] if reserved["data"]["risk_tier"] in ("T1", "T2", "T3") else "T3"
    except Exception:
        tier = "T3"
    if resolved is None or not opens_gate(reserved, resolved, world_owner, team_lead, policy):
        return gate(tier, (), "L1", None, "gate_not_opened")
    return Decision("run", tier, (), "L1", None, dict(resolved["authz"]), 0, None, "gate_approved")
