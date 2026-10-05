"""PI-02, PI-03 (docs/security/p4-policy-invariants.md), FR-HIL-03: only approve on the same
gate/card/outbox from someone allowed to open it (PRD 10.1) opens a gate; edit, hold, no answer
or anyone else leaves it shut. A gate never times out to go and is never delegated to the
Director — open_gate only ever hands authority to a person or a Team Lead (PI-01, PI-16)."""

from __future__ import annotations

import pytest
import tilo_policy
from _policy_lib import OWNER

# approval.requested.approver is the owner's assignment of the gate (ADR-0006).
APPROVER = {"user": "u_approver", "assigned_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"}}
GATE = {"gate_id": "G1", "card_id": "01JB5VQ0000000000000009001", "outbox_id": "01JB5VQ0000000000000009002"}


def _reserved(*, risk_tier="T2", approver=None, team_lead_allowance=None):
    return {
        "type": "approval.requested",
        "authz": None,
        "data": {
            **GATE,
            "action_type": "send_email",
            "risk_tier": risk_tier,
            "irreversible": True,
            "item": {"artifact_id": "art_reply_draft", "version": 1},
            "approver": approver,
            "team_lead": team_lead_allowance,
        },
    }


def _resolved(
    *, by="person", ref=OWNER, option="approve", channel="web", pin_verified=True, at="2026-09-29T09:32:09.500Z"
):
    return {
        "type": "approval.resolved",
        "authz": {"by": by, "ref": ref, "at": at},
        "data": {**GATE, "option": option, "channel": channel, "pin_verified": pin_verified},
    }


def test_FR_HIL_03_PI_02_owner_approves_and_the_gate_opens():
    decision = tilo_policy.open_gate(_reserved(), _resolved(ref=OWNER), world_owner=OWNER)
    assert decision.outcome == "run"
    assert decision.authz == {"by": "person", "ref": OWNER, "at": "2026-09-29T09:32:09.500Z"}


def test_FR_HIL_03_PI_02_named_approver_approves_and_the_gate_opens():
    resolved = _resolved(ref="u_approver")
    decision = tilo_policy.open_gate(_reserved(approver=APPROVER), resolved, world_owner=OWNER)
    assert decision.outcome == "run"
    assert decision.authz["ref"] == "u_approver"


def test_PI_02_edit_writes_nothing():
    decision = tilo_policy.open_gate(_reserved(), _resolved(option="edit"), world_owner=OWNER)
    assert decision.outcome == "gate"
    assert decision.authz is None


def test_PI_02_PI_03_hold_writes_nothing_and_no_default_go():
    decision = tilo_policy.open_gate(_reserved(), _resolved(option="hold"), world_owner=OWNER)
    assert decision.outcome == "gate"
    assert decision.authz is None


def test_PI_02_never_answered_stays_shut():
    decision = tilo_policy.open_gate(_reserved(), None, world_owner=OWNER)
    assert decision.outcome == "gate"
    assert decision.authz is None


def test_PI_02_answer_from_someone_else_opens_nothing():
    """Not the owner and not the named Approver — a Viewer or anyone else."""
    decision = tilo_policy.open_gate(_reserved(approver=APPROVER), _resolved(ref="u_random_viewer"), world_owner=OWNER)
    assert decision.outcome == "gate"


def test_PI_02_answer_from_another_person_when_no_approver_is_named_opens_nothing():
    decision = tilo_policy.open_gate(_reserved(approver=None), _resolved(ref="u_not_owner"), world_owner=OWNER)
    assert decision.outcome == "gate"


@pytest.mark.parametrize("risk_tier", ["T1", "T2", "T3"])
@pytest.mark.parametrize("pin_verified", [True, False])
@pytest.mark.parametrize("ref", [OWNER, "u_approver"])
def test_PI_04_SEC_06_an_answer_over_whatsapp_opens_nothing(risk_tier, pin_verified, ref):
    """ADR-0019 (SD-01, SEC-06 amended): a gate opens only in a signed-in web or mobile-web
    session. `whatsapp` stays enum-valid, so a legacy or forged answer over it is refused, PIN or not."""
    reserved = _reserved(risk_tier=risk_tier, approver=APPROVER)
    resolved = _resolved(ref=ref, channel="whatsapp", pin_verified=pin_verified)
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER)
    assert (decision.outcome, decision.authz) == ("gate", None)


@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_PI_04_SEC_06_t3_gate_in_a_signed_in_session_opens_without_a_pin(channel):
    """SEC-06 as amended: no PIN; the signed-in session is the control."""
    reserved = _reserved(risk_tier="T3", approver=APPROVER)
    resolved = _resolved(ref="u_approver", channel=channel, pin_verified=False)
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER)
    assert decision.outcome == "run"


def test_PI_02_team_lead_in_domain_the_policy_allows_opens_the_gate():
    allowance = {"domain": "operations", "policy_id": "pol_drive_saves"}
    reserved = _reserved(team_lead_allowance=allowance)
    reserved["data"]["action_type"] = "save_file"
    resolved = _resolved(by="team_lead", ref="tl_ops_1", at="2026-09-29T09:45:00.000Z")
    team_lead = {
        "id": "tl_ops_1",
        "user": "u_ops_lead",
        "domain": "operations",
        "assigned_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"},
    }
    policy = {
        "id": "pol_drive_saves",
        "owner": OWNER,
        "action_type": "save_file",
        "team_lead_domains": ["operations"],
        "created_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"},
        "changed_by": None,
        "expiry": None,
        "history": [{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "Created", "level": "L1"}],
    }
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER, team_lead=team_lead, policy=policy)
    assert decision.outcome == "run"
    assert decision.authz == {"by": "team_lead", "ref": "tl_ops_1", "at": "2026-09-29T09:45:00.000Z"}
    assert decision.policy_id is None, "PI-16: a Team Lead's approval is stamped by team_lead, never by policy"


def test_PI_02_team_lead_outside_the_named_domain_opens_nothing():
    allowance = {"domain": "operations", "policy_id": "pol_drive_saves"}
    reserved = _reserved(team_lead_allowance=allowance)
    reserved["data"]["action_type"] = "save_file"
    resolved = _resolved(by="team_lead", ref="tl_finance_1", at="2026-09-29T09:45:00.000Z")
    team_lead = {
        "id": "tl_finance_1",
        "user": "u_finance_lead",
        "domain": "finance",
        "assigned_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"},
    }
    policy = {
        "id": "pol_drive_saves",
        "owner": OWNER,
        "action_type": "save_file",
        "team_lead_domains": ["operations"],
        "created_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"},
        "changed_by": None,
        "expiry": None,
        "history": [{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "Created", "level": "L1"}],
    }
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER, team_lead=team_lead, policy=policy)
    assert decision.outcome == "gate"


def test_PI_02_team_lead_the_policy_does_not_allow_opens_nothing():
    allowance = {"domain": "operations", "policy_id": "pol_drive_saves"}
    reserved = _reserved(team_lead_allowance=allowance)
    reserved["data"]["action_type"] = "save_file"
    resolved = _resolved(by="team_lead", ref="tl_ops_1", at="2026-09-29T09:45:00.000Z")
    team_lead = {
        "id": "tl_ops_1",
        "user": "u_ops_lead",
        "domain": "operations",
        "assigned_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"},
    }
    policy = {
        "id": "pol_drive_saves",
        "owner": OWNER,
        "action_type": "save_file",
        "team_lead_domains": [],  # the owner's policy does not list "operations"
        "created_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"},
        "changed_by": None,
        "expiry": None,
        "history": [{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "Created", "level": "L1"}],
    }
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER, team_lead=team_lead, policy=policy)
    assert decision.outcome == "gate"


def test_PI_02_team_lead_assigned_by_someone_other_than_the_owner_opens_nothing():
    allowance = {"domain": "operations", "policy_id": "pol_drive_saves"}
    reserved = _reserved(team_lead_allowance=allowance)
    reserved["data"]["action_type"] = "save_file"
    resolved = _resolved(by="team_lead", ref="tl_ops_1", at="2026-09-29T09:45:00.000Z")
    team_lead = {
        "id": "tl_ops_1",
        "user": "u_ops_lead",
        "domain": "operations",
        "assigned_by": {"by": "u_not_the_owner", "at": "2026-09-29T09:00:00.000Z"},
    }
    policy = {
        "id": "pol_drive_saves",
        "owner": OWNER,
        "action_type": "save_file",
        "team_lead_domains": ["operations"],
        "created_by": {"by": OWNER, "at": "2026-09-29T09:00:00.000Z"},
        "changed_by": None,
        "expiry": None,
        "history": [{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "Created", "level": "L1"}],
    }
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER, team_lead=team_lead, policy=policy)
    assert decision.outcome == "gate"


def test_PI_03_gate_is_never_delegated_to_the_director():
    """approval.resolved's authz.by is only ever "person" or "team_lead" (event registry
    authz_by); a "policy" or any other value opens nothing (never a model, never the
    Director)."""
    resolved = _resolved(by="policy", ref="pol_autopilot_l2")
    decision = tilo_policy.open_gate(_reserved(), resolved, world_owner=OWNER)
    assert decision.outcome == "gate"
    assert decision.authz is None
