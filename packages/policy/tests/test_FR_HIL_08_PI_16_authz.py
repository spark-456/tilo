"""FR-HIL-08 (PRD 10.4, 10.6): "authz on every side-effect event; Autonomy log with undo or
report" — 100% of side-effect events in the eval set carry authz. PI-16: every side-effect event
carries authz, its by is one the registry allows for the type, and a policy's authz.ref equals
its policy_id. Here: every non-gate Decision (run, run_after_undo) carries authz, never by a
model, and a policy-authorised Decision's authz.ref equals the covering policy_id.
"""

from __future__ import annotations

import tilo_policy
from conftest import OWNER, WORLD, base_facts, base_instruction, base_policy

NOW = "2026-09-29T09:42:16.000Z"


def _table(risk_table_path):
    return tilo_policy.load_risk_table(risk_table_path)


def _proposal(instruction=None):
    return tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**base_facts()),
        item={"artifact_id": "art_followup_reply", "version": 1},
        credits=1,
        instruction=instruction,
    )


def test_FR_HIL_08_PI_16_l2_run_after_undo_carries_authz_by_policy_ref_equal_to_policy_id(risk_table_path):
    table = _table(risk_table_path)
    instruction = base_instruction()
    policy = base_policy(id_="pol_autopilot_l2", level="L2")
    decision = tilo_policy.decide(
        _proposal(instruction), table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW
    )
    assert decision.outcome == "run_after_undo"
    assert decision.authz is not None
    assert decision.authz["by"] == "policy"
    assert decision.authz["ref"] == policy["id"] == decision.policy_id


def test_FR_HIL_08_PI_16_l3_run_carries_authz_by_policy_ref_equal_to_policy_id(risk_table_path):
    table = _table(risk_table_path)
    policy = base_policy(
        id_="pol_status_updates",
        action_type="post_status_update",
        level="L3",
        recipients=("teammate@example.org",),
        history=[{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created at L3", "level": "L3"}],
    )
    proposal = tilo_policy.Proposal(
        world_id=WORLD,
        action_type="post_status_update",
        connector="gmail",
        district="D1",
        destination=None,
        facts=tilo_policy.SideEffectFacts(
            **base_facts(recipients=("teammate@example.org",), known_recipients=("teammate@example.org",))
        ),
        item={"artifact_id": "art_status_update", "version": 1},
        credits=1,
        instruction=None,
    )
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "run"
    assert decision.authz == {"by": "policy", "ref": "pol_status_updates", "at": NOW}
    assert decision.policy_id == "pol_status_updates"


def test_FR_HIL_08_never_authorised_by_a_model(risk_table_path):
    """authz.by is always "person", "policy" or "team_lead" — a model is never an authority
    (common.schema.json#/$defs/authz). No Decision this engine returns may set authz.by to
    anything else."""
    table = _table(risk_table_path)
    instruction = base_instruction()
    policy = base_policy(id_="pol_autopilot_l2", level="L2")
    decision = tilo_policy.decide(
        _proposal(instruction), table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW
    )
    assert decision.authz["by"] in {"person", "policy", "team_lead"}


def test_FR_HIL_08_gate_decisions_carry_no_authz_at_all(risk_table_path):
    """A gate authorises nothing (PI-01): its Decision.authz is None, not a placeholder, and
    never claims a model made it."""
    table = _table(risk_table_path)
    decision = tilo_policy.decide(_proposal(), table=table, policies=[], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"
    assert decision.authz is None
