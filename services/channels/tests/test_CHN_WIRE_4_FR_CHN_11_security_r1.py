"""CHN-WIRE-4 security review r1 (FR-CHN-11; PRD 11.6 "no send after cancel"; OB-01, OB-03; BQ-245, BQ-246, BQ-249).
Two instances interleave around a card's decision: a slow `decide`, an enqueue in flight, a slow store read. Whatever
the order, a re-decision or a drop is recorded at the slot of the head that was judged, a drop is never recorded over a
stored entry, no L2 entry outlives the card's Cancel or Edit, and an entry is never created outside its decision's
freshness bound. Fake engine, `FakeOutbox`, fake clock; no network, no real mail.
"""

from __future__ import annotations

from typing import Any

import pytest
from _chn11_lib import BENIGN_V2, POLICY_ID, USER, autopilot_module
from _chn13_lib import iso
from _chn_wire4_lib import attempt, card_id_of, decision, gate_decision, make_w4


def bound() -> int:
    return autopilot_module().DECISION_MAX_AGE_S


def pending(*, later: tuple[str, ...] = ()) -> tuple[Any, Any, Any, str]:
    """A card decided at T0 whose first enqueue failed (outbox down); the outbox is up again, `bound()` s later."""
    w4 = make_w4()
    ctx, result = w4.drafted(w4.thread(*later))
    w4.outbox.down = True
    attempt(lambda: w4.ap.preview(USER, ctx, result))
    w4.outbox.down = False
    assert w4.entries() == [] and w4.ap.policy_applied(USER, card_id_of(ctx)) is not None
    return w4, ctx, result, card_id_of(ctx)


def no_send_after_cancel(w4: Any, card_id: str) -> None:
    assert w4.ap.cancel(USER, card_id).status == "cancelled"
    assert w4.ap.stop_state(USER, card_id) == "cancelled"
    w4.clock.advance(3600)
    w4.outbox.dispatch_due()
    assert w4.outbox.sent == [], "no mail after the owner's Cancel"


# -- R1: a slow decide must not drop a card whose entry another instance has stored ---------------------------------


def test_CHN_WIRE_4_FR_CHN_11_r1_a_slow_gate_never_drops_a_card_another_instance_enqueued() -> None:
    w4, ctx, result, card_id = pending()
    w4.clock.advance(bound() + 1)
    inner = {"on": False}

    def respond(user_id: str, proposal: Any) -> Any:
        if inner["on"]:
            return decision(w4.clock)
        inner["on"] = True
        w4.new_ap().preview(USER, ctx, result)  # instance A: decides again (clean), stores #pol1, enqueues
        return gate_decision()  # instance B's own answer arrives late and gates

    w4.policy.respond = respond
    card = w4.new_ap().preview(USER, ctx, result)

    (entry,) = w4.entries()
    assert card.level == "L2" and w4.ap.policy_applied(USER, card_id) is not None
    assert w4.ap.policy_applied(USER, card_id)["authz"] == entry["authz"]
    assert w4.of_type("approval.requested") == [], "no gate for an outbox id that holds a scheduled entry"
    no_send_after_cancel(w4, card_id)


# -- R2: a drop racing an enqueue in flight --------------------------------------------------------------------------


def race_inside_enqueue(w4: Any, ctx: Any, result: Any, *, answer_lost: bool) -> None:
    """Instance A judged the decision fresh and is inside the enqueue; instance B, 1 s later, judges it stale and the
    policy gates: B drops the card. Then A's entry lands (and A optionally never hears: `answer_lost`)."""
    real, fired = w4.outbox.enqueue, []

    def enqueue(entry: dict, evidence: dict) -> dict:
        if not fired:
            fired.append(1)
            w4.clock.advance(1)
            w4.policy.respond = lambda user_id, proposal: gate_decision()
            assert w4.new_ap().preview(USER, ctx, result).level == "L1"
        stored = real(entry, evidence)
        if answer_lost:
            raise ConnectionError("the answer was lost")
        return stored

    w4.outbox.enqueue = enqueue


def test_CHN_WIRE_4_FR_CHN_11_r2_an_entry_that_lands_after_a_drop_is_stopped_by_its_own_enqueuer() -> None:
    w4, ctx, result, card_id = pending()
    w4.clock.advance(bound())  # exactly the bound: fresh for A
    race_inside_enqueue(w4, ctx, result, answer_lost=False)

    card = w4.new_ap().preview(USER, ctx, result)

    assert card.level == "L1" and w4.ap.policy_applied(USER, card_id) is None
    assert [e["state"] for e in w4.entries()] == ["cancelled"], "an L2 entry under a dropped card is stopped"
    no_send_after_cancel(w4, card_id)


def test_CHN_WIRE_4_FR_CHN_11_r2_cancel_on_a_dropped_card_stops_an_entry_whose_enqueuer_never_heard() -> None:
    w4, ctx, result, card_id = pending()
    w4.clock.advance(bound())
    race_inside_enqueue(w4, ctx, result, answer_lost=True)

    attempt(lambda: w4.new_ap().preview(USER, ctx, result))

    assert [e["state"] for e in w4.entries()] == ["scheduled"] and w4.ap.policy_applied(USER, card_id) is None
    no_send_after_cancel(w4, card_id)


def test_CHN_WIRE_4_FR_CHN_11_r2_edit_on_a_dropped_card_stops_the_old_draft() -> None:
    w4, ctx, result, card_id = pending(later=(BENIGN_V2,))
    w4.clock.advance(bound())
    race_inside_enqueue(w4, ctx, result, answer_lost=True)
    attempt(lambda: w4.new_ap().preview(USER, ctx, result))
    assert [e["state"] for e in w4.entries()] == ["scheduled"]

    new = w4.ap.edit(USER, card_id, "add a thank you", instruction_id="ins-edit-r2")

    assert new is not None and new.level == "L1"
    assert [e["state"] for e in w4.entries()] == ["cancelled"]
    w4.clock.advance(3600)
    w4.outbox.dispatch_due()
    assert w4.outbox.sent == [], "the superseded draft is never sent"


# -- freshness is judged on the clock read that stamps created_at ----------------------------------------------------


def slow_second_stop_read(w4: Any, seconds: int) -> None:
    """The card store hangs `seconds` on its second `#stop` read: the one at E2, after the freshness check."""
    real, reads = w4.cards.get, []

    def get(user_id: str, key: str) -> Any:
        if key.endswith("#stop"):
            reads.append(1)
            if len(reads) == 2:
                w4.clock.advance(seconds)
        return real(user_id, key)

    w4.cards.get = get


def test_CHN_WIRE_4_FR_CHN_11_a_slow_store_read_never_stretches_the_bound_the_entry_waits_for_a_new_decision() -> None:
    w4, ctx, result, card_id = pending()
    w4.clock.advance(bound() - 1)
    slow_second_stop_read(w4, 20)

    card = w4.new_ap().preview(USER, ctx, result)

    (entry,) = w4.entries()
    assert len(w4.policy.calls) == 2, "the stale decision was made again"
    assert card.level == "L2" and entry["authz"]["at"] == iso(w4.clock()) == entry["created_at"]
    assert entry["authz"] == w4.ap.policy_applied(USER, card_id)["authz"]


def test_CHN_WIRE_4_FR_CHN_11_a_slow_store_read_with_a_revocation_in_between_writes_no_entry() -> None:
    w4, ctx, result, card_id = pending()
    w4.clock.advance(bound() - 1)
    slow_second_stop_read(w4, 20)
    w4.policy.respond = lambda user_id, proposal: gate_decision()

    card = w4.new_ap().preview(USER, ctx, result)

    assert card.level == "L1" and w4.entries() == []
    assert w4.new_ap().send(USER, card_id).status == "refused"
    w4.clock.advance(3600)
    w4.outbox.dispatch_due()
    assert w4.outbox.sent == []


# -- the cheap follow-ups --------------------------------------------------------------------------------------------


class Evil(str):
    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


class EvilDict(dict):
    def __ne__(self, other: object) -> bool:
        return False


UNUSABLE = {
    "window_above_the_contract_cap": lambda c: decision(c, undo_window_s=3601),
    "impossible_date": lambda c: decision(
        c, authz={"by": "policy", "ref": POLICY_ID, "at": "2026-02-30T09:00:00.000Z"}
    ),
    "year_zero": lambda c: decision(c, authz={"by": "policy", "ref": POLICY_ID, "at": "0000-01-01T00:00:00.000Z"}),
    "str_subclass_tier": lambda c: decision(c, tier=Evil("T3")),
    "str_subclass_outcome": lambda c: decision(c, outcome=Evil("gate")),
    "dict_subclass_authz": lambda c: decision(c, authz=EvilDict(by="person", ref="u_sarah", at=iso(c()))),
    "extra_authz_key": lambda c: decision(c, authz={"by": "policy", "ref": POLICY_ID, "at": iso(c()), "x": 1}),
}


@pytest.mark.parametrize("case", sorted(UNUSABLE))
def test_CHN_WIRE_4_FR_CHN_11_r1_an_unusable_decision_is_l1_and_never_raises_out_of_preview(case: str) -> None:
    w4 = make_w4()
    w4.policy.respond = lambda user_id, proposal: UNUSABLE[case](w4.clock)
    ctx, result = w4.pair(w4.thread())

    card = w4.ap.preview(USER, ctx, result)

    assert card.level == "L1" and w4.entries() == [] and w4.ap.policy_applied(USER, card.card_id) is None


def test_CHN_WIRE_4_FR_CHN_11_replays_the_outbox_keeps_refusing_add_a_bounded_number_of_decisions() -> None:
    """Each replay after the bound used to add a slot and a policy.applied for an entry that never exists."""
    w4, ctx, result, card_id = pending()
    w4.outbox.down = True
    for _ in range(8):
        w4.clock.advance(bound() + 1)
        attempt(lambda: w4.new_ap().preview(USER, ctx, result))

    assert len(w4.of_type("policy.applied")) <= 4 and len(w4.policy.calls) <= 4, "a bounded number of decisions"
    assert w4.entries() == [] and w4.new_ap().preview(USER, ctx, result).level == "L1"
    assert len(w4.of_type("approval.requested")) == 1
    w4.outbox.down = False
    w4.clock.advance(3600)
    w4.outbox.dispatch_due()
    assert w4.entries() == [] and w4.outbox.sent == []
