"""FR-HIL-05, PI-21, BQ-57 (#28): until ADR-0013 (Proposed) records the action an L2 instruction
asked for without a model, no instruction opens a send. Every L2-covered send waits at a gate,
whatever the instruction looks like. L3, L1 and L0 behave as before; the OB-01 validator keeps
its interim rule until ADR-0013 adds crossref cases.
"""

from __future__ import annotations

import pytest
import tilo_policy
from _policy_lib import OWNER, WORLD, applied_entry, base_facts, base_instruction, base_policy
from tilo_policy import coverage

NOW = "2026-09-29T09:42:16.000Z"
L0_HISTORY = [{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Observe", "level": "L0"}]

# Every shape of instruction the interim rule could once have accepted, and the ways it fails.
SHAPES = {
    "none": None,
    "whatsapp_typed": base_instruction(channel="whatsapp", type_="channel.message_in"),
    "web_signed_in": base_instruction(channel="web", type_="world.requested"),
    "mobile_web": base_instruction(channel="mobile_web", type_="world.requested"),
    "email": base_instruction(channel="email", type_="channel.message_in"),
    "someone_else": base_instruction(actor="u_someone_else"),
    "other_thread": base_instruction(destination="thread-other-2"),
    "after_the_send": base_instruction(ts="2026-09-29T09:50:00.000Z"),
}


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


def _decide(instruction, policy, applied=()):
    table = tilo_policy.load_risk_table()
    return tilo_policy.decide(
        _proposal(instruction), table=table, policies=[policy], world_owner=OWNER, applied=list(applied), now=NOW
    )


def test_FR_HIL_05_PI_21_the_engine_starts_with_no_action_recorded():
    assert coverage.L2_ACTION_RECORDED is False


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("undo_window_s", [1, 60, 3600])
def test_FR_HIL_05_PI_21_l2_send_waits_at_a_gate_under_every_instruction_shape(shape, undo_window_s):
    decision = _decide(SHAPES[shape], base_policy(level="L2", undo_window_s=undo_window_s))
    assert decision.outcome == "gate"
    assert decision.level == "L2"
    assert decision.reason == "l2_instruction_required"
    assert decision.authz is None
    assert decision.scheduled_at is None


def test_FR_HIL_05_PI_21_an_unused_valid_instruction_still_gates_and_a_used_one_too():
    instruction = SHAPES["whatsapp_typed"]
    policy = base_policy(level="L2")
    earlier = [applied_entry(policy_id=policy["id"], at="2026-09-29T09:35:00.000Z", instruction_id=instruction["id"])]
    assert _decide(instruction, policy).outcome == "gate"
    assert _decide(instruction, policy, earlier).outcome == "gate"


def test_FR_HIL_05_PI_21_the_interim_rule_stays_as_an_extra_check_once_an_action_is_recorded(monkeypatch):
    policy = base_policy(level="L2")
    monkeypatch.setattr(coverage, "L2_ACTION_RECORDED", True)
    assert _decide(SHAPES["whatsapp_typed"], policy).outcome == "run_after_undo"
    for shape in ("none", "email", "someone_else", "other_thread", "after_the_send"):
        assert _decide(SHAPES[shape], policy).outcome == "gate", shape


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_FR_HIL_05_PI_21_l3_still_runs_without_an_instruction(shape):
    decision = _decide(SHAPES[shape], base_policy(level="L3"))
    assert (decision.outcome, decision.level, decision.reason) == ("run", "L3", "l3_run")


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_FR_HIL_05_PI_21_l1_still_gates_as_no_covering_policy(shape):
    decision = _decide(SHAPES[shape], base_policy(level="L1"))
    assert (decision.outcome, decision.level, decision.reason) == ("gate", "L1", "no_covering_policy")


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_FR_HIL_05_PI_21_l0_still_drafts_only(shape):
    decision = _decide(SHAPES[shape], base_policy(level="L0", history=L0_HISTORY))
    assert (decision.outcome, decision.reason) == ("draft_only", "l0_draft_only")
