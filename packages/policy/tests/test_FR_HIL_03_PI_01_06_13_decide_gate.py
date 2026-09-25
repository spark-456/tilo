"""FR-HIL-03 / FR-HIL-04 (PRD 10.4, 10.6): gates hold every side effect not covered by a policy,
and a policy never authorises T3. PI-01 (a gate authorises nothing / authz only on a run path),
PI-06 (policy coverage: action type, owner, stamps, scope, timing), PI-07 (T3 always gates),
PI-13 (level in force at decision time; several covering policies, lowest level wins).
"""

from __future__ import annotations

import tilo_policy
from conftest import OWNER, WORLD, base_facts, base_instruction, base_policy

NOW = "2026-09-29T09:42:16.000Z"


def _table(risk_table_path):
    return tilo_policy.load_risk_table(risk_table_path)


def _proposal(**overrides):
    base = dict(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**base_facts()),
        item={"artifact_id": "art_followup_reply", "version": 1},
        credits=1,
        instruction=None,
    )
    base.update(overrides)
    return tilo_policy.Proposal(**base)


def test_FR_HIL_04_PI_07_t3_action_always_gates_even_with_a_permissive_policy(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal(facts=tilo_policy.SideEffectFacts(**base_facts(deletion=True)))
    permissive = base_policy(level="L3", per_day=None, credits=None)
    decision = tilo_policy.decide(proposal, table=table, policies=[permissive], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"
    assert decision.tier == "T3"
    assert decision.authz is None
    assert decision.policy_id is None


def test_FR_HIL_03_PI_06_no_policy_at_all_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal()
    decision = tilo_policy.decide(proposal, table=table, policies=[], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"
    assert decision.authz is None
    assert decision.level == "L1"


def test_FR_HIL_03_PI_06_recipient_out_of_scope_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal(facts=tilo_policy.SideEffectFacts(**base_facts(recipients=("other@elsewhere.org",))))
    policy = base_policy(domains=("example.com",))
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_06_connector_out_of_scope_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal(connector="outlook")
    policy = base_policy(connectors=("gmail",))
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_06_district_out_of_scope_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal(district="D9")
    policy = base_policy(districts=("D1",))
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_06_expired_policy_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal()
    policy = base_policy(expiry="2026-09-01T00:00:00.000Z")
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_06_policy_created_after_send_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal()
    policy = base_policy(created_at="2026-09-30T00:00:00.000Z")
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_06_policy_owned_by_someone_else_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal()
    policy = base_policy(owner="u_someone_else")
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_13_history_entry_by_someone_else_covers_nothing(risk_table_path):
    """PI-13: a policy record anyone but the owner created, changed or raised again covers
    nothing, whatever `owner` says (only the owner creates and changes a policy, PRD 10.1)."""
    table = _table(risk_table_path)
    proposal = _proposal()
    policy = base_policy(
        history=[
            {"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created", "level": "L2"},
            {"by": "u_intruder", "at": "2026-09-29T09:40:00.000Z", "change": "Raised again", "level": "L2"},
        ]
    )
    policy["changed_by"] = {"by": "u_intruder", "at": "2026-09-29T09:40:00.000Z"}
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_13_level_field_disagreeing_with_last_history_entry_covers_nothing(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal()
    policy = base_policy(level="L2")
    policy["history"] = [{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created", "level": "L3"}]
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_03_L0_policy_is_draft_only(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal()
    policy = base_policy(
        level="L0", history=[{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Observe", "level": "L0"}]
    )
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "draft_only"
    assert decision.authz is None
    assert decision.policy_id == policy["id"]


def test_FR_HIL_03_PI_13_several_covering_policies_lowest_level_wins(risk_table_path):
    """PI-13: when more than one policy covers the same action type and scope, the lowest level
    in force wins (fail safe) — here L2 (with a usable instruction) beats a broader L3 rule."""
    table = _table(risk_table_path)
    instr = base_instruction()
    proposal = _proposal(instruction=instr)
    l2 = base_policy(id_="pol_l2", level="L2", undo_window_s=60)
    l3 = base_policy(
        id_="pol_l3",
        level="L3",
        history=[{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created", "level": "L3"}],
    )
    decision = tilo_policy.decide(proposal, table=table, policies=[l3, l2], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "run_after_undo"
    assert decision.policy_id == "pol_l2"


def test_FR_HIL_08_PI_01_authz_is_None_on_every_gate_and_draft_only_decision(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal()
    gated = tilo_policy.decide(proposal, table=table, policies=[], world_owner=OWNER, applied=[], now=NOW)
    assert gated.outcome == "gate" and gated.authz is None

    l0 = base_policy(
        level="L0", history=[{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Observe", "level": "L0"}]
    )
    drafted = tilo_policy.decide(proposal, table=table, policies=[l0], world_owner=OWNER, applied=[], now=NOW)
    assert drafted.outcome == "draft_only" and drafted.authz is None
