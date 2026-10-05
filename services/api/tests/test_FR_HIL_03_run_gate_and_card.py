"""CL-INT-2 / FR-HIL-03, FR-HIL-04, FR-HIL-01 (PRD 10.2 "Approval gate", 10.3, 10.4; PI-01..PI-04; CR-07; HR-7):
the plan's irreversible step (a send through the mock connector) stops at a gate. `approval.requested` and a gate
card the owner reads over the cards API (#121) are the only things written; nothing reaches the outbox until a person
approves. The owner's approval opens the gate; hold keeps it held; no one else can answer it. T3 always needs a
person, even with an owner policy in force. Shapes and sequence: API_CL_INT_2.md.
"""

from __future__ import annotations

import pytest
from _cards_lib import card_errors
from _clint2_lib import (
    DESTINATION,
    DRAFT_REF,
    FLOW_USER,
    KNOWN_RECIPIENT,
    MOCK_ID,
    NEW_RECIPIENT,
    OTHER_USER,
    POOL,
    assert_stream_valid,
    build_run_flow,
    index_of,
    only,
    schema_errors,
    wait_for,
)
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

PAST_THE_GATE = ("approval.resolved", "data.transfer", "artifact.delivered", "world.completed")


def _nothing_past_the_gate(rf):
    stream = rf.quiet_stream()
    assert not [e["type"] for e in stream if e["type"] in PAST_THE_GATE], [e["type"] for e in stream]
    assert rf.outbox_store.all_entries() == []
    assert rf.adapter.sent == []


def test_FR_HIL_03_the_irreversible_step_stops_at_a_gate_with_a_card_and_nothing_is_sent(run_flow, registry):
    requested, card = run_flow.run_to_gate()

    data = requested["data"]
    assert data["gate_id"] == "G1" and data["action_type"] == "send_email"
    assert data["risk_tier"] == "T3"  # a recipient the owner has not written to before (PRD 10.4)
    assert data["irreversible"] is True  # the connector declares send_email irreversible
    assert data["item"] == DRAFT_REF and data["card_id"] == card["id"]
    assert data["approver"] is None and data["team_lead"] is None
    assert requested["authz"] is None  # a request authorises nothing
    assert not card_errors(card, registry), card_errors(card, registry)
    assert card["world_id"] == run_flow.world_id and card["run_id"] == run_flow.store.worlds[run_flow.world_id].run_id
    gate = card["gate"]
    assert gate["id"] == "G1" and gate["risk_tier"] == "T3" and gate["irreversible"] is True
    assert gate["action"]["type"] == "send_email" and gate["action"]["connector"] == MOCK_ID
    assert gate["action"]["destination"] == DESTINATION and gate["recipients"] == [NEW_RECIPIENT]
    assert gate["action"]["item"]["artifact_id"] == DRAFT_REF["artifact_id"]
    assert card["safe_default"] == "hold"  # gates never time out to "go" (PRD 10.3)
    assert {"approve", "hold"} <= {o["id"] for o in card["options"]}
    assert not [o for o in card["options"] if o["suggested"] and o["irreversible"]]  # CR: never suggest the send
    assert "web" in card["answer_channels"]
    (call,) = run_flow.resolver_calls
    assert call["unit"] == "U4" and call["action_type"] == "send_email" and call["item"] == DRAFT_REF
    _nothing_past_the_gate(run_flow)  # FR-HIL-03: the action waits; HR-1: nothing is reported done
    assert run_flow.delivery().status_code == 409


def test_FR_HIL_01_only_the_owner_reads_the_gate_card(run_flow):
    _, card = run_flow.run_to_gate()

    run_flow.as_member("u_viewer", "viewer")
    assert run_flow.cards().status_code == 403
    run_flow.as_member(OTHER_USER, "owner")
    other = run_flow.cards()
    assert other.status_code in (403, 404) and card["id"] not in other.text
    run_flow.as_member("u_approver", "approver")  # the owner assigned them nothing
    unassigned = run_flow.cards()
    assert unassigned.status_code == 200 and unassigned.json() == []
    run_flow.as_member()
    run_flow.world_id, real = "w_not_this_one", run_flow.world_id
    assert run_flow.cards().status_code == 404  # a member of the world in the path only
    run_flow.world_id = real
    run_flow.flow.sign_out()
    assert run_flow.cards().status_code == 401
    run_flow.as_member()
    assert [c["id"] for c in run_flow.cards().json() if c["kind"] == "gate"] == [card["id"]]


def test_FR_HIL_03_the_owner_approving_resolves_the_gate_with_person_authz_and_enqueues_one_entry(run_flow, registry):
    requested, card = run_flow.run_to_gate()

    response = run_flow.answer(card["id"], "approve")

    assert response.status_code == 200 and response.json() == {"outcome": "answered"}
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    events = assert_stream_valid(run_flow, registry)
    resolved = only(events, "approval.resolved")
    assert resolved["authz"]["by"] == "person" and resolved["authz"]["ref"] == FLOW_USER
    assert resolved["data"] == {
        "gate_id": "G1", "card_id": card["id"], "outbox_id": requested["data"]["outbox_id"],
        "option": "approve", "channel": "web", "pin_verified": False,
    }  # fmt: skip
    assert index_of(events, requested) < index_of(events, resolved)
    (entry,) = run_flow.outbox_store.all_entries()  # exactly one entry
    assert schema_errors("outbox", entry) == []
    assert entry["id"] == requested["data"]["outbox_id"]
    assert entry["world_id"] == run_flow.world_id
    assert entry["run_id"] == run_flow.store.worlds[run_flow.world_id].run_id
    assert (entry["action_type"], entry["connector"], entry["destination"]) == ("send_email", MOCK_ID, DESTINATION)
    assert entry["recipients"] == [NEW_RECIPIENT] and entry["attachments"] == [] and entry["item"] == DRAFT_REF
    assert entry["risk_tier"] == "T3" and entry["modifiers"] == ["new_recipients"]
    assert entry["authz"] == resolved["authz"]  # the person's approval, not a policy's and not the Director's
    assert entry["state"] == "sent" and entry["undo_window_s"] == 0


def test_FR_HIL_03_after_approval_the_mock_sends_once_and_the_run_is_delivered(run_flow, registry):
    requested, _ = run_flow.run_to_completion()

    events = assert_stream_valid(run_flow, registry)
    resolved, transfer = only(events, "approval.resolved"), only(events, "data.transfer")
    delivered, completed = only(events, "artifact.delivered"), only(events, "world.completed")
    order = [index_of(events, e) for e in (requested, resolved, transfer, delivered, completed)]
    assert order == sorted(order) and len(set(order)) == 5
    outbox_id = requested["data"]["outbox_id"]
    assert transfer["data"] == {
        "connector": MOCK_ID, "action_type": "send_email", "direction": "out", "artifact": DRAFT_REF,
        "outbox_id": outbox_id, "risk_tier": "T3",
    }  # fmt: skip
    assert (
        transfer["authz"] == resolved["authz"] and transfer["authz"]["by"] == "person"
    )  # HR-7: linked to the approval
    assert delivered["data"] == {"artifact": DRAFT_REF, "format": "email", "outbox_id": outbox_id}
    assert delivered["cause"] == transfer["id"] and delivered["authz"] is None  # EV-14: the notice, not the side effect
    assert completed["data"]["deliverable_count"] == 1
    (sent,) = run_flow.adapter.sent
    assert sent["thread_id"] == DESTINATION and sent["recipients"] == [NEW_RECIPIENT] and sent["item"] == DRAFT_REF
    (entry,) = run_flow.outbox_store.all_entries()
    assert sent["idempotency_key"] == entry["idempotency_key"]


def test_FR_HIL_03_hold_keeps_the_action_held_and_the_card_open(run_flow):
    _, card = run_flow.run_to_gate()

    held = run_flow.answer(card["id"], "hold")

    assert held.status_code == 200
    _nothing_past_the_gate(run_flow)  # CR-07: only approve opens a gate
    assert [c["id"] for c in run_flow.cards().json() if c["kind"] == "gate"] == [card["id"]]
    assert run_flow.delivery().status_code == 409
    assert run_flow.answer(card["id"], "approve").status_code == 200  # still the person's to open
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    assert len(run_flow.adapter.sent) == 1


@pytest.mark.parametrize(("user", "role"), [(OTHER_USER, "owner"), ("u_viewer", "viewer"), ("u_approver", "approver")])
def test_FR_HIL_03_no_one_but_the_owner_can_answer_the_gate_card(run_flow, user, role):
    _, card = run_flow.run_to_gate()

    run_flow.as_member(user, role)
    refused = run_flow.answer(card["id"], "approve")
    named = run_flow.flow.client.post(
        f"/worlds/{run_flow.world_id}/cards/{card['id']}/answer", json={"option": "approve", "actor": FLOW_USER}
    )  # a body cannot name who answers

    assert refused.status_code in (403, 404) and named.status_code in (403, 404, 422)
    run_flow.as_member()
    _nothing_past_the_gate(run_flow)
    assert [c["id"] for c in run_flow.cards().json() if c["kind"] == "gate"] == [card["id"]]


def _l3_send_policy():
    """The owner's valid L3 policy for send_email on the mock connector (history stamped by the owner)."""
    stamp = {"by": FLOW_USER, "at": "2026-09-29T09:30:00.000Z"}
    return {
        "id": "pol_send_mock",
        "owner": FLOW_USER,
        "action_type": "send_email",
        "scope": {"connectors": [MOCK_ID], "recipients": [], "domains": [], "districts": []},
        "limits": {"per_day": 5, "credits": None},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": "L3",
        "undo_window_s": 60,
        "expiry": None,
        "notify_channel": "email",
        "team_lead_domains": [],
        "created_by": stamp,
        "changed_by": stamp,
        "history": [{**stamp, "change": "Raised to L3", "level": "L3"}],
    }


def test_FR_HIL_04_a_T3_send_still_waits_for_a_person_with_an_owner_L3_policy_in_force(run_flow):
    import tilo_policy
    from tilo_api.events import now

    policy = _l3_send_policy()
    assert schema_errors("policy", policy) == []
    known = tilo_policy.SideEffectFacts(recipients=(KNOWN_RECIPIENT,), known_recipients=(KNOWN_RECIPIENT,))
    proposal = tilo_policy.Proposal(
        world_id="w_check", action_type="send_email", connector=MOCK_ID, district="D2", destination=DESTINATION,
        facts=known, item=DRAFT_REF, credits=0, instruction=None,
    )  # fmt: skip
    table = tilo_policy.load_risk_table()
    covered = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=FLOW_USER, applied=[], now=now())
    assert covered.outcome in (
        "run",
        "run_after_undo",
    )  # the policy is real: it does cover a T2 send to a known contact
    run_flow.store.policies[policy["id"]] = policy

    requested, _ = run_flow.run_to_gate()  # the recipient is new to the owner, so the action is T3

    assert requested["data"]["risk_tier"] == "T3"
    assert run_flow.events("policy.applied") == []
    _nothing_past_the_gate(run_flow)


@settings(max_examples=10, deadline=None, derandomize=True, phases=(Phase.generate,))  # a failure needs no shrinking
@given(
    recipients=st.lists(st.sampled_from(POOL), min_size=1, max_size=3, unique=True),
    known=st.sets(st.sampled_from(POOL)),
    failing=st.sets(st.sampled_from(["U1", "U2", "U3"])),
)
def test_FR_HIL_04_property_no_send_happens_before_a_person_approves(repo_root, recipients, known, failing):
    rf = build_run_flow(repo_root, covered=True)
    try:
        rf.recipients, rf.known_recipients, rf.runner.fail = recipients, sorted(known), set(failing)
        rf.start()
        assert rf.approve().status_code == 200
        wait_for(lambda: rf.events("world.started"), what="world.started")
        stream = rf.quiet_stream(0.4)

        assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))  # strictly increasing, gap-free
        assert len({e["id"] for e in stream}) == len(stream)
        assert not [e for e in stream if e["type"] in PAST_THE_GATE]
        assert rf.outbox_store.all_entries() == [] and rf.adapter.sent == []  # no person has approved anything
        if failing:  # a failed dependency skips the sender, so there is nothing to approve
            assert "U4" not in rf.runner.ran and not rf.events("approval.requested")
            return
        (requested,) = rf.events("approval.requested")
        gate_cards = [c for c in rf.cards().json() if c["kind"] == "gate"]
        assert [c["id"] for c in gate_cards] == [requested["data"]["card_id"]]
        assert rf.answer(gate_cards[0]["id"], "approve").status_code == 200
        wait_for(lambda: rf.events("world.completed"), what="world.completed")
        final = rf.stream()
        assert only(final, "approval.resolved")["authz"]["by"] == "person"
        assert index_of(final, only(final, "approval.resolved")) < index_of(final, only(final, "data.transfer"))
        assert len(rf.outbox_store.all_entries()) == 1 and len(rf.adapter.sent) == 1
    finally:
        rf.close()
