"""FR-HIL-05 (PRD 10.4, 10.6): "Given an L2 email policy, when the user instructs a reply, then
it sends after the 60 s window unless cancelled." PI-08 (L2 needs the owner's own instruction
naming this exact destination), PI-09 (the instruction must come from a channel with a known
sender — web/mobile_web signed in, or the owner's bound WhatsApp number; never email), PI-10
(each instruction opens at most one entry, cancelled sends included), PI-12 (the undo window is
kept: >= 1 s, scheduled_at = created_at (here `now`) + undo_window_s).
"""

from __future__ import annotations

import pytest
import tilo_policy
from _policy_lib import OWNER, WORLD, applied_entry, base_facts, base_instruction, base_policy

NOW = "2026-09-29T09:42:16.000Z"


def _table(risk_table_path):
    return tilo_policy.load_risk_table(risk_table_path)


def _proposal(instruction=None, **overrides):
    base = dict(
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
    base.update(overrides)
    return tilo_policy.Proposal(**base)


def _l2_policy(**overrides):
    return base_policy(**{"id_": "pol_autopilot_l2", "level": "L2", "undo_window_s": 60, **overrides})


@pytest.mark.usefixtures("l2_action_recorded")
def test_FR_HIL_05_PI_08_PI_12_whatsapp_instruction_runs_after_undo_window_default_60s(risk_table_path):
    table = _table(risk_table_path)
    instruction = base_instruction(channel="whatsapp", type_="channel.message_in")
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "run_after_undo"
    assert decision.undo_window_s == 60
    assert decision.scheduled_at == "2026-09-29T09:43:16.000Z"
    assert decision.authz == {"by": "policy", "ref": "pol_autopilot_l2", "at": NOW}
    assert decision.policy_id == "pol_autopilot_l2"


@pytest.mark.usefixtures("l2_action_recorded")
def test_FR_HIL_05_PI_09_web_signed_in_instruction_also_counts(risk_table_path):
    table = _table(risk_table_path)
    instruction = base_instruction(channel="web", type_="world.requested")
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "run_after_undo"


@pytest.mark.usefixtures("l2_action_recorded")
def test_FR_HIL_05_PI_09_mobile_web_instruction_also_counts(risk_table_path):
    table = _table(risk_table_path)
    instruction = base_instruction(channel="mobile_web", type_="world.requested")
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "run_after_undo"


def test_FR_HIL_05_PI_09_email_instruction_opens_nothing(risk_table_path):
    """An email's sender is not authenticated (PRD 10.3, 11.1): a channel.message_in or
    world.requested over email is never an instruction, whoever its actor is."""
    table = _table(risk_table_path)
    instruction = base_instruction(channel="email", type_="channel.message_in")
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_05_PI_08_no_instruction_at_all_gates(risk_table_path):
    table = _table(risk_table_path)
    proposal = _proposal(instruction=None)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_05_PI_08_instruction_from_someone_else_gates(risk_table_path):
    table = _table(risk_table_path)
    instruction = base_instruction(actor="u_someone_else")
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_05_PI_08_instruction_about_another_thread_gates(risk_table_path):
    """The instruction's destination must equal the proposal's — a draft nobody asked for or an
    instruction about another thread opens nothing."""
    table = _table(risk_table_path)
    instruction = base_instruction(destination="thread-other-2")
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_05_PI_08_instruction_given_after_the_send_gates(risk_table_path):
    table = _table(risk_table_path)
    instruction = base_instruction(ts="2026-09-29T09:50:00.000Z")  # after NOW
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"


def test_FR_HIL_05_PI_10_instruction_already_used_by_an_earlier_send_gates(risk_table_path):
    """PI-10: each instruction opens at most one entry; a redraft after Undo (the earlier send
    cancelled or not) needs a new instruction or a gate."""
    table = _table(risk_table_path)
    instruction = base_instruction()
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy()
    earlier = [
        applied_entry(policy_id="pol_autopilot_l2", at="2026-09-29T09:35:00.000Z", instruction_id=instruction["id"])
    ]
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=earlier, now=NOW)
    assert decision.outcome == "gate"


@pytest.mark.usefixtures("l2_action_recorded")
def test_FR_HIL_05_PI_12_undo_window_at_least_1s_is_kept_from_the_policy(risk_table_path):
    table = _table(risk_table_path)
    instruction = base_instruction()
    proposal = _proposal(instruction=instruction)
    policy = _l2_policy(undo_window_s=1)
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "run_after_undo"
    assert decision.undo_window_s == 1
    assert decision.scheduled_at == "2026-09-29T09:42:17.000Z"
