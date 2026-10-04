"""FR-HIL-03, FR-HIL-04 (PRD 10.4, 10.6) property tests, Hypothesis:

(a) no T3 proposal ever gets an outcome other than "gate" from decide(), whatever policies,
    levels or scopes are generated, and the only way to "run" a T3 is open_gate with a human
    authz (person or team_lead), never a policy.
(b) no recipient outside known_recipients is ever added without a person: a proposal with a new
    recipient never runs via decide() (new_recipients is one of the six T3 modifiers, so this is
    (a) specialised to that one modifier, kept separate because FR-HIL-03's acceptance test names
    new recipients explicitly, PRD 10.4).
(c) removing a policy mid-run (dropping it from `policies`, or appending an L1 history entry —
    revocation or Stop all) makes the next send wait at a gate, while a send decided before
    stays covered (PI-13, "revocable in one tap").
"""

from __future__ import annotations

import pytest
import tilo_policy
from _policy_lib import OWNER, WORLD, base_facts, base_instruction, base_policy
from hypothesis import given, settings
from hypothesis import strategies as st

NOW = "2026-09-29T09:42:16.000Z"
LATER = "2026-09-29T10:00:00.000Z"

_email = st.emails()
_level = st.sampled_from(["L0", "L1", "L2", "L3"])


def _table(risk_table_path):
    return tilo_policy.load_risk_table(risk_table_path)


def _proposal_with_modifier(recipients, known_recipients, deletion, attachments):
    facts_kwargs = base_facts(recipients=tuple(recipients), known_recipients=tuple(known_recipients))
    if deletion:
        facts_kwargs["deletion"] = True
    if attachments:
        facts_kwargs["attachments"] = ({"artifact_id": "art_x", "version": 1},)
    return tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**facts_kwargs),
        item={"artifact_id": "art_x", "version": 1},
        credits=1,
        instruction=None,
    )


def _arbitrary_policy(level, index):
    return base_policy(
        id_=f"pol_arbitrary_{index}",
        level=level,
        undo_window_s=60,
        history=[{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "Created", "level": level}],
    )


@given(
    known=st.lists(_email, min_size=0, max_size=2, unique=True),
    extra=_email,
    deletion=st.booleans(),
    levels=st.lists(_level, min_size=0, max_size=3),
)
@settings(max_examples=40, deadline=None)
def test_FR_HIL_04_PI_07_t3_proposal_never_runs_via_decide(risk_table_path, known, extra, deletion, levels):
    """(a)+(b): recipients include one address not in known_recipients (or deletion is set) —
    either way the proposal is T3 (PI-07) — so whatever policies (any levels, any count) are
    passed, decide() must return "gate", never run/run_after_undo/draft_only."""
    table = _table(risk_table_path)
    recipients = [*known, extra] if extra not in known else [*known, extra + ".new"]
    proposal = _proposal_with_modifier(recipients, known, deletion=deletion or extra not in known, attachments=False)
    tier = table.assess(proposal.action_type, proposal.facts).tier
    assert tier == "T3", "the generated proposal must actually be T3 for this property to mean anything"
    policies = [_arbitrary_policy(level, i) for i, level in enumerate(levels)]
    decision = tilo_policy.decide(proposal, table=table, policies=policies, world_owner=OWNER, applied=[], now=NOW)
    assert decision.outcome == "gate"
    assert decision.authz is None
    assert decision.policy_id is None


@given(ref=st.sampled_from(["policy", "team_lead_but_wrong_id"]))
@settings(max_examples=10, deadline=None)
def test_FR_HIL_04_PI_01_open_gate_t3_never_runs_except_by_a_human_authz(ref):
    """The only way a T3 gate ever opens is open_gate with authz.by "person" or "team_lead"
    (never "policy" — approval.resolved's registry entry only allows authz_by
    [person, team_lead], so any other by never opens it)."""
    reserved = {
        "type": "approval.requested",
        "authz": None,
        "data": {
            "gate_id": "G1",
            "card_id": "01JB5VQ0000000000000009001",
            "outbox_id": "01JB5VQ0000000000000009002",
            "action_type": "send_email",
            "risk_tier": "T3",
            "irreversible": True,
            "item": {"artifact_id": "art_x", "version": 1},
            "approver": None,
            "team_lead": None,
        },
    }
    resolved = {
        "type": "approval.resolved",
        "authz": {"by": "policy" if ref == "policy" else "team_lead", "ref": ref, "at": NOW},
        "data": {
            "gate_id": "G1",
            "card_id": "01JB5VQ0000000000000009001",
            "outbox_id": "01JB5VQ0000000000000009002",
            "option": "approve",
            "channel": "web",
            "pin_verified": True,
        },
    }
    decision = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER)
    assert decision.outcome == "gate", (
        "never authorised by a policy, and a team_lead with no matching record/policy opens nothing"
    )
    assert decision.authz is None


@pytest.mark.usefixtures("l2_action_recorded")
def test_FR_HIL_03_PI_13_revoking_the_covering_policy_gates_the_next_send_but_not_an_earlier_one(risk_table_path):
    """(c): a T2 policy covers a send at NOW; the owner then revokes it (an L1 history entry
    appended after NOW, PI-13 "revocable in one tap"). A send decided at NOW, from the record as it
    stood then, runs. Once the record carries the revocation, every decision gates, at LATER and
    also at NOW: a live decision never reads a policy back to a level it no longer has, so a retry,
    a replay or a clock behind the kill switch cannot send after it (FR-HIL-03, FR-HIL-07). The
    historical reading (a send made before a revocation stays covered) is check_entry's, over the
    crossref case policy_reply_sent_before_revocation."""
    table = _table(risk_table_path)
    instruction = base_instruction()
    created = {"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created at L2", "level": "L2"}
    revoked = {"by": OWNER, "at": "2026-09-29T09:55:00.000Z", "change": "Revoked", "level": "L1"}
    policy_after_revocation = base_policy(id_="pol_autopilot_l2", level="L1", history=[created, revoked])

    proposal = tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**base_facts()),
        item={"artifact_id": "art_x", "version": 1},
        credits=1,
        instruction=instruction,
    )

    policy_before_revocation = base_policy(id_="pol_autopilot_l2", level="L2", history=[created])
    before = tilo_policy.decide(
        proposal, table=table, policies=[policy_before_revocation], world_owner=OWNER, applied=[], now=NOW
    )
    assert before.outcome == "run_after_undo", "a send decided before the revocation runs (PI-13)"

    replayed = tilo_policy.decide(
        proposal, table=table, policies=[policy_after_revocation], world_owner=OWNER, applied=[], now=NOW
    )
    assert replayed.outcome == "gate", "a revoked record never covers a send, whatever now says"

    after = tilo_policy.decide(
        proposal, table=table, policies=[policy_after_revocation], world_owner=OWNER, applied=[], now=LATER
    )
    assert after.outcome == "gate", "the next send after a revocation waits at a gate (FR-HIL-03, FR-HIL-07)"


@pytest.mark.usefixtures("l2_action_recorded")
def test_FR_HIL_03_PI_06_dropping_the_policy_from_the_list_also_gates(risk_table_path):
    """(c), the simpler half: the policy engine has no memory between calls — a policy that is
    simply not passed in `policies` covers nothing, the same as one that was revoked."""
    table = _table(risk_table_path)
    instruction = base_instruction()
    policy = base_policy(id_="pol_autopilot_l2", level="L2")
    proposal = tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**base_facts()),
        item={"artifact_id": "art_x", "version": 1},
        credits=1,
        instruction=instruction,
    )
    covered = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW)
    assert covered.outcome == "run_after_undo"

    removed = tilo_policy.decide(proposal, table=table, policies=[], world_owner=OWNER, applied=[], now=NOW)
    assert removed.outcome == "gate"
