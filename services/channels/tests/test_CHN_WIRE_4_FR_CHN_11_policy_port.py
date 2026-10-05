"""CHN-WIRE-4 (FR-CHN-11; issue #307 plan ticket 4, issue #256 gate 3; PRD 10.4 L2, 11.4 Undo; OB-01, OB-02, OB-05):
the autopilot's autonomy policy is asked `decide(user_id, proposal)` with a `tilo_policy.Proposal` that carries the
entry's recipients, connector, district, destination and item; the engine's `Decision` (its `policy.applied` part, its
`authz` and its `undo_window_s`) is stored in the card at decide time and stamps the L2 entry; `scheduled_at` is
`created_at + undo_window_s`. The `level()` hint keeps working for a policy object that has no `decide`.

A scripted FAKE engine answers `run_after_undo` here (the real engine still gates every L2 send until ADR-0013: see
test_CHN_WIRE_4_FR_CHN_11_fail_closed.py). Production-mode Autopilot (no `fake_evidence`), `FakeOutbox`; no network,
no real mail. API: API_CHN_WIRE_4.md.
"""

from __future__ import annotations

import copy

import pytest
import tilo_policy
from _channels_lib import T0
from _chn11_lib import BENIGN_V2, DAVID, POLICY_ID, SARAH, USER, FakePolicy, parse_ts
from _chn13_lib import iso
from _chn_wire4_lib import (
    DISTRICT,
    OMIT,
    DecideAndLevelStub,
    decision,
    make_w4,
    policy_part_errors,
)
from tilo_channels.autopilot_gate import gate_id_for

CONTACTS = (DAVID, SARAH)


def previewed(policy=None, *, to=(DAVID,), cc=()):
    w4 = make_w4(policy)
    thread = w4.thread()
    ctx, result = w4.pair(thread, to=to, cc=cc)
    card = w4.ap.preview(USER, ctx, result)
    return w4, thread, ctx, result, card


@pytest.mark.parametrize(
    ("to", "cc"), [((DAVID,), ()), ((DAVID,), (SARAH,)), ((DAVID, SARAH), (DAVID,)), ((SARAH,), (DAVID, SARAH))]
)
def test_CHN_WIRE_4_FR_CHN_11_proposal_carries_the_final_entry_recipients_connector_district_destination_item(
    to: tuple[str, ...], cc: tuple[str, ...]
) -> None:
    """Given a ready T2 draft of the owner's instruction; when the card is decided; then the policy is asked once, as
    `decide(user_id, Proposal)`, and the proposal equals what the entry will say (recipients: To then Cc, each once)."""
    w4, thread, ctx, result, card = previewed(to=to, cc=cc)

    assert len(w4.policy.calls) == 1
    user_id, proposal = w4.policy.calls[0]
    assert user_id == USER and isinstance(proposal, tilo_policy.Proposal)
    (entry,) = w4.entries()
    assert entry["recipients"] == list(dict.fromkeys(to + cc)), "recipients: To then Cc, each once (OB-05)"
    assert proposal.facts.recipients == tuple(entry["recipients"])
    assert (proposal.world_id, proposal.action_type, proposal.connector) == (entry["world_id"], "send_email", "gmail")
    assert proposal.connector == entry["connector"] and proposal.district == DISTRICT
    assert proposal.destination == entry["destination"] == thread.thread_id
    assert proposal.item == entry["item"] == {"artifact_id": result.draft.artifact_id, "version": result.draft.version}
    facts = proposal.facts
    assert facts.new_recipients == () and facts.attachments == ()
    assert not (facts.external_share or facts.deletion or facts.money_or_legal or facts.safety_flags)
    assert proposal.credits >= 0


def test_CHN_WIRE_4_FR_CHN_11_district_is_a_constructor_argument_defaulting_to_d1() -> None:
    """The proposal's district is the Autopilot's `district` keyword; with none given it is "D1" (BQ-242)."""
    w4 = make_w4()
    w4.ap = w4.new_ap(district=OMIT)
    thread = w4.thread()
    w4.ap.preview(USER, *w4.pair(thread))
    assert [p.district for p in w4.policy.proposals()] == ["D1"]


def test_CHN_WIRE_4_FR_CHN_11_decision_is_stored_in_the_card_as_a_valid_policy_applied_part() -> None:
    """The decision's `policy.applied` part is in the card doc from the moment of the decision, readable from any
    instance, valid against its contract, and names the gate, the reserved entry id, the instruction and the item."""
    w4, thread, ctx, result, card = previewed()
    part = w4.ap.policy_applied(USER, card.card_id)

    assert part is not None and policy_part_errors(part) == []
    data = part["data"]
    assert part["authz"] == {"by": "policy", "ref": POLICY_ID, "at": iso(T0)}
    assert data["policy_id"] == POLICY_ID and data["level"] == "L2" and data["risk_tier"] == "T2"
    assert data["gate_id"] == gate_id_for(card.card_id)
    assert data["outbox_id"] == card.outbox_id
    assert data["instruction_id"] == ctx.instruction_id
    assert (data["action_type"], data["connector"], data["district"]) == ("send_email", "gmail", DISTRICT)
    assert data["destination"] == thread.thread_id
    assert data["item"] == {"artifact_id": result.draft.artifact_id, "version": result.draft.version}
    assert data["undo_window_s"] == 60

    again = w4.new_ap().policy_applied(USER, card.card_id)
    assert again == part, "the same part from any instance"
    part["authz"]["at"] = "tampered"
    assert w4.ap.policy_applied(USER, card.card_id)["authz"]["at"] == iso(T0), "a copy, not the stored one"


@pytest.mark.parametrize("window", [30, 60, 90, 600])
def test_CHN_WIRE_4_FR_CHN_11_entry_is_stamped_from_the_stored_decision_with_its_undo_window(window: int) -> None:
    """The entry's authz is the decision's, copied; its window is the decision's; scheduled_at = created_at + window."""
    w4 = make_w4()
    w4.policy.respond = lambda user_id, proposal: decision(w4.clock, undo_window_s=window)
    ctx, result = w4.pair(w4.thread())
    card = w4.ap.preview(USER, ctx, result)

    (entry,) = w4.entries()
    part = w4.ap.policy_applied(USER, card.card_id)
    assert entry["authz"] == part["authz"] == {"by": "policy", "ref": POLICY_ID, "at": iso(T0)}
    assert entry["undo_window_s"] == window == part["data"]["undo_window_s"] == card.undo_window_s
    assert (parse_ts(entry["scheduled_at"]) - parse_ts(entry["created_at"])).total_seconds() == window
    assert card.scheduled_at == entry["scheduled_at"] and entry["state"] == "scheduled"
    assert entry["id"] == card.outbox_id == part["data"]["outbox_id"]
    assert (card.level, card.tier) == ("L2", "T2")
    w4.clock.advance(window - 1)
    assert w4.outbox.dispatch_due() == [], "nothing leaves before the window ends"
    w4.clock.advance(1)
    assert [e["id"] for e in w4.outbox.dispatch_due()] == [card.outbox_id]


def test_CHN_WIRE_4_FR_CHN_11_entry_authz_at_is_the_decision_time_never_now() -> None:
    """A decision stamped 5 s before the enqueue stamps the entry with that time, not the enqueue time."""
    w4 = make_w4()
    w4.policy.respond = lambda user_id, proposal: decision(
        w4.clock, authz={"by": "policy", "ref": POLICY_ID, "at": iso(w4.clock() - 5)}
    )
    ctx, result = w4.pair(w4.thread())
    card = w4.ap.preview(USER, ctx, result)

    (entry,) = w4.entries()
    assert entry["authz"]["at"] == iso(T0 - 5) != entry["created_at"], "authz.at is the decision's (OB-01)"
    assert entry["authz"] == w4.ap.policy_applied(USER, card.card_id)["authz"]


def test_CHN_WIRE_4_FR_CHN_11_policy_applied_is_emitted_once_before_the_entry_and_no_gate_is_raised() -> None:
    w4, thread, ctx, result, card = previewed()

    (emitted,) = w4.of_type("policy.applied")
    assert emitted == w4.ap.policy_applied(USER, card.card_id) and policy_part_errors(emitted) == []
    assert w4.of_type("approval.requested") == [] and w4.ap.approval_requested(USER, card.card_id) is None
    assert emitted["authz"] == w4.entries()[0]["authz"], "HR-7: the entry's authz is the recorded event's"


def test_CHN_WIRE_4_FR_CHN_11_replay_and_second_instance_reuse_the_stored_decision() -> None:
    """Preview again, Send, and a restarted instance: one decide call, one policy.applied, one entry (OB-03)."""
    w4, thread, ctx, result, card = previewed()
    stored = w4.ap.policy_applied(USER, card.card_id)
    other = w4.new_ap()
    w4.clock.advance(20)  # inside the freshness bound

    again = other.preview(USER, ctx, result)
    sent = other.send(USER, card.card_id)
    w4.ap.preview(USER, ctx, result)

    assert len(w4.policy.calls) == 1, "a replay never asks the policy again"
    assert again.card_id == card.card_id and again.outbox_id == card.outbox_id and again.level == "L2"
    assert sent.status == "scheduled" and sent.outbox_id == card.outbox_id
    assert len(w4.entries()) == 1 and len(w4.of_type("policy.applied")) == 1
    assert other.policy_applied(USER, card.card_id) == stored


def test_CHN_WIRE_4_FR_CHN_11_a_redraft_after_edit_never_rides_the_old_decision() -> None:
    """Edit cancels the L2 entry and redrafts: the new card waits for a person (no policy question, no policy part)."""
    w4 = make_w4()
    thread = w4.thread(BENIGN_V2)
    ctx, result = w4.drafted(thread)
    card = w4.ap.preview(USER, ctx, result)
    assert card.level == "L2" and len(w4.policy.calls) == 1

    new = w4.ap.edit(USER, card.card_id, "add a thank you", instruction_id="ins-edit-w4")

    assert new is not None and new.card_id != card.card_id
    assert (new.level, new.undo_window_s, new.scheduled_at) == ("L1", 0, None)
    assert len(w4.policy.calls) == 1, "a redraft is a new proposal that always waits for a person"
    assert w4.ap.policy_applied(USER, new.card_id) is None
    assert w4.ap.approval_requested(USER, new.card_id) is not None
    assert w4.outbox.state(card.outbox_id) == "cancelled"
    assert len(w4.entries()) == 1


def test_CHN_WIRE_4_FR_CHN_11_t3_is_never_l2_even_when_the_policy_says_run_after_undo() -> None:
    """A recipient that is neither a contact nor known from the thread makes the card T3 (FR-CHN-12): it waits for a
    person, no entry, no policy part, whatever a (faulty) engine answers (OB-04, BQ-152)."""
    w4 = make_w4(district=OMIT)
    stranger = "new.person@elsewhere.example"
    ctx, result = w4.pair(w4.thread(), to=(DAVID,), cc=(stranger,))
    card = w4.ap.preview(USER, ctx, result)

    assert (card.tier, card.level, card.scheduled_at) == ("T3", "L1", None)
    assert "new_recipients" in card.modifiers
    assert w4.entries() == [] and w4.ap.policy_applied(USER, card.card_id) is None
    assert w4.of_type("policy.applied") == []
    assert w4.ap.approval_requested(USER, card.card_id) is not None
    w4.clock.advance(3600)
    w4.outbox.dispatch_due()
    assert w4.entries() == [] and w4.outbox.sent == []


def test_CHN_WIRE_4_FR_CHN_11_a_blank_instruction_is_never_put_to_the_policy() -> None:
    """BQ-222 still holds: nothing a person wrote never rides L2, so the policy is not even asked."""
    w4 = make_w4(district=OMIT)
    ctx, result = w4.pair(w4.thread(), instruction="   ")
    card = w4.ap.preview(USER, ctx, result)

    assert card.level == "L1" and w4.entries() == [] and w4.policy.calls == []


def test_CHN_WIRE_4_FR_CHN_11_a_policy_with_only_the_level_hint_keeps_working() -> None:
    """Compat (API_CHN_WIRE_4.md): an object without `decide` is asked `level()` exactly as before, and the entry is
    stamped as before (policy, its id, now); nothing is stored as a decision."""
    w4 = make_w4(lambda clock: FakePolicy("L2"), district=OMIT)
    ctx, result = w4.pair(w4.thread())
    card = w4.ap.preview(USER, ctx, result)

    assert (card.level, card.undo_window_s) == ("L2", 60)
    (entry,) = w4.entries()
    assert entry["authz"]["by"] == "policy" and entry["authz"]["ref"] == POLICY_ID
    assert w4.policy.calls == [(USER, "send_email")]
    assert w4.ap.policy_applied(USER, card.card_id) is None and w4.of_type("policy.applied") == []


def test_CHN_WIRE_4_FR_CHN_11_a_policy_with_both_methods_is_asked_decide_only() -> None:
    w4 = make_w4(DecideAndLevelStub)
    stub = w4.policy
    ctx, result = w4.pair(w4.thread())
    card = w4.ap.preview(USER, ctx, result)

    assert card.level == "L2" and len(stub.calls) == 1 and stub.level_calls == [], "the hint is never asked"
    assert w4.ap.policy_applied(USER, card.card_id) is not None


def test_CHN_WIRE_4_FR_CHN_11_stored_decision_is_a_copy_the_stub_cannot_change_later() -> None:
    """Mutating the Decision's authz dict after the call (a shared object) changes neither the card nor the entry."""
    w4 = make_w4()
    kept = {}

    def respond(user_id, proposal):
        kept["decision"] = decision(w4.clock)
        return kept["decision"]

    w4.policy.respond = respond
    ctx, result = w4.pair(w4.thread())
    card = w4.ap.preview(USER, ctx, result)
    before = copy.deepcopy(w4.ap.policy_applied(USER, card.card_id))
    kept["decision"].authz["ref"] = "pol_someone_else"
    kept["decision"].authz["at"] = "2099-01-01T00:00:00.000Z"

    assert w4.ap.policy_applied(USER, card.card_id) == before
    assert w4.entries()[0]["authz"] == before["authz"]
