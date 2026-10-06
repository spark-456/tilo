"""FR-CHN-11, CHN-WIRE-4 follow-ups from the #333 security review r2 (issue #343; PRD 11.4 Preview and Undo, 11.6 "no
send after cancel"; OB-02, OB-03; honesty rules HR-1 to HR-7, PRD 9.4; BQ-245, BQ-246, BQ-249).

Four items, all fail closed today and none reachable in production until a real policy adapter is wired:

1. A replay or a Send tap on an L2 card whose entry is already stored returns that entry at any age, instead of
   raising RuntimeError after StaleDecision x3; a stale decision with no stored entry still creates nothing.
2. A race drop emits its `approval.requested` only after the post-create stored check has stopped a raced entry.
3. `send()` never answers "queued" for an entry that was cancelled after a race drop.
4. `_usable` accepts a `policy_id` only if `type(d.policy_id) is str` (a str subclass, bool, int or None fails closed).

Fake engine, `FakeOutbox`, fake clock; no network, no real mail. Helpers come from the CHN-WIRE-4 test lib.
"""

from __future__ import annotations

from typing import Any

import pytest
from _chn11_lib import POLICY_ID, USER, autopilot_module
from _chn13_lib import iso
from _chn_wire1_lib import resolved
from _chn_wire4_lib import assert_no_send_ever, attempt, card_id_of, decision, gate_decision, make_w4


def bound() -> int:
    return autopilot_module().DECISION_MAX_AGE_S  # PRD default 30 s (BQ-245)


def states(w4: Any) -> list[str]:
    return [e["state"] for e in w4.entries()]


def no_send(w4: Any) -> None:
    w4.clock.advance(3600)
    w4.outbox.dispatch_due()
    assert w4.outbox.sent == [], "nothing may be sent"


def pending() -> tuple[Any, Any, Any, str]:
    """A card decided at T0 whose first enqueue failed (outbox down); the outbox is up again, no entry exists."""
    w4 = make_w4()
    ctx, result = w4.drafted(w4.thread())
    w4.outbox.down = True
    attempt(lambda: w4.ap.preview(USER, ctx, result))
    w4.outbox.down = False
    card_id = card_id_of(ctx)
    assert w4.entries() == [] and w4.ap.policy_applied(USER, card_id) is not None
    return w4, ctx, result, card_id


# -- 1. entry_for's freshness check must not run for an already-stored entry -----------------------------------------


def scheduled_card() -> tuple[Any, Any, Any, str, dict]:
    """An L2 card whose entry is stored and still `scheduled` (60 s window), decided at T0."""
    w4 = make_w4()
    ctx, result = w4.drafted(w4.thread())
    card = w4.ap.preview(USER, ctx, result)
    (entry,) = w4.entries()
    assert card.level == "L2" and entry["state"] == "scheduled" and len(w4.policy.calls) == 1
    return w4, ctx, result, card.card_id, entry


@pytest.mark.parametrize("age", [bound() + 1, 45, 59])
def test_FR_CHN_11_wire4_preview_replay_after_the_bound_returns_the_stored_entry(age: int) -> None:
    """Given an L2 card whose entry is stored; when a Pub/Sub redelivery replays preview more than 30 s after the
    decision (inside the 60 s undo window); then the card is the same L2 card, no error, no new entry or decision."""
    w4, ctx, result, card_id, entry = scheduled_card()
    w4.clock.advance(age)

    replay = w4.new_ap().preview(USER, ctx, result)  # RuntimeError "did not settle" today

    assert replay.level == "L2" and replay.outbox_id == entry["id"] and replay.scheduled_at == entry["scheduled_at"]
    assert w4.entries() == [entry], "the same one entry, untouched"
    assert len(w4.policy.calls) == 1, "nothing is decided again once the card's key is stored"
    assert w4.of_type("policy.applied") == w4.of_type("policy.applied")[:1]
    w4.clock.advance(3600)
    w4.outbox.dispatch_due()
    assert len(w4.outbox.sent) == 1, "the stored entry is still the one that sends"


@pytest.mark.parametrize("age", [bound() + 1, 45, 59])
def test_FR_CHN_11_wire4_send_tap_after_the_bound_reports_the_stored_scheduled_entry(age: int) -> None:
    """Given the same card; when its owner taps Send more than 30 s after the decision; then the answer is
    "scheduled" with the stored entry's id, not an exception."""
    w4, ctx, result, card_id, entry = scheduled_card()
    w4.clock.advance(age)

    outcome = w4.new_ap().send(USER, card_id)  # RuntimeError "did not settle" today

    assert outcome.status == "scheduled" and outcome.outbox_id == entry["id"]
    assert w4.entries() == [entry] and len(w4.policy.calls) == 1


def test_FR_CHN_11_wire4_a_stale_decision_with_no_stored_entry_still_creates_nothing() -> None:
    """The fail-closed side stays: every store read hangs past the bound (a hung card store), so no entry may be
    created from the stale authorisation, by preview or by Send; whatever is raised, nothing is sent."""
    w4 = make_w4()
    ctx, result = w4.drafted(w4.thread())
    real = w4.cards.get

    def get(user_id: str, key: str) -> Any:
        if key.endswith("#stop"):
            w4.clock.advance(bound() + 1)
        return real(user_id, key)

    w4.cards.get = get

    attempt(lambda: w4.ap.preview(USER, ctx, result))
    attempt(lambda: w4.new_ap().preview(USER, ctx, result))
    attempt(lambda: w4.new_ap().send(USER, card_id_of(ctx)))

    assert w4.entries() == [], "an entry is never created outside its decision's freshness bound"
    assert_no_send_ever(w4)


# -- 2. a drop's approval.requested comes after the post-create stored check -----------------------------------------


def drop_race(w4: Any, ctx: Any, result: Any, b_emit: Any, *, answer_lost: bool = False) -> None:
    """Instance A judged the decision fresh (age exactly the bound) and is inside its enqueue. Instance B, 1 s later,
    judges it stale, the policy gates and B creates the drop slot; A's entry lands right after that create, before B's
    post-create stored check. B's `approval.requested` goes to `b_emit`. With `answer_lost` A never hears that its
    enqueue worked, so A's own dropped check never stops the entry: only B's stored check can (r2 review, probe X2)."""
    real_enqueue, real_create, held = w4.outbox.enqueue, w4.cards.create, {}

    def create(user_id: str, key: str, value: dict) -> bool:
        created = real_create(user_id, key, value)
        if created and key.endswith("#pol1") and "entry" in held and "landed" not in held:
            held["landed"] = real_enqueue(*held["entry"])  # A's entry lands after B's drop slot exists
        return created

    def enqueue(entry: dict, evidence: dict) -> dict:
        if "entry" not in held:
            held["entry"] = (entry, evidence)
            w4.clock.advance(1)
            w4.policy.respond = lambda user_id, proposal: gate_decision()
            attempt(lambda: w4.new_ap(emit=b_emit).preview(USER, ctx, result))
        stored = real_enqueue(entry, evidence)
        if answer_lost:
            raise ConnectionError("the answer was lost")
        return stored

    w4.cards.create, w4.outbox.enqueue = create, enqueue
    w4.clock.advance(bound())
    attempt(lambda: w4.new_ap().preview(USER, ctx, result))
    assert "landed" in held, "setup: the entry must land between B's create and B's stored check"


def test_FR_CHN_11_wire4_a_drop_emits_its_gate_only_after_the_raced_entry_is_stopped() -> None:
    """HR (PRD 9.4): `approval.requested` for an outbox id must not be shown while a scheduled entry holds it."""
    w4, ctx, result, card_id = pending()
    at_emit: list[list[str]] = []
    record = lambda part: at_emit.append(states(w4)) if part["type"] == "approval.requested" else None  # noqa: E731
    drop_race(w4, ctx, result, record, answer_lost=True)

    assert states(w4) == ["cancelled"], "an L2 entry under a dropped card is stopped"
    assert all("scheduled" not in seen for seen in at_emit), f"the gate was emitted over a scheduled entry: {at_emit}"
    no_send(w4)


def test_FR_CHN_11_wire4_a_failing_gate_emit_after_a_drop_never_leaves_the_raced_entry_scheduled() -> None:
    """The gate's emit raises (or the instance dies there): the stored check and the stop must already be done."""
    w4, ctx, result, card_id = pending()

    def failing_emit(part: dict) -> None:
        if part["type"] == "approval.requested":
            raise ConnectionError("the event sink is down")

    drop_race(w4, ctx, result, failing_emit, answer_lost=True)

    assert states(w4) == ["cancelled"], "the entry is stopped before anything that can fail"
    assert w4.ap.stop_state(USER, card_id) == "cancelled"
    no_send(w4)


# -- 3. send() never says "queued" for a cancelled entry -------------------------------------------------------------


def test_FR_CHN_11_wire4_owner_send_after_a_race_drop_is_refused_not_queued_for_a_cancelled_entry() -> None:
    """Given a race drop whose raced entry was stopped (cancelled); when the owner then taps Send on the L1 card with
    a valid approval; then the answer reports the entry's real state (refused), never "queued"; nothing is sent."""
    w4, ctx, result, card_id = pending()
    drop_race(w4, ctx, result, w4.events)
    assert states(w4) == ["cancelled"]
    ap = w4.new_ap()
    requested = ap.approval_requested(USER, card_id)
    assert requested is not None, "setup: the dropped card carries its gate"
    approval = resolved(requested, w4)

    outcome = attempt(lambda: ap.send(USER, card_id, approval))

    assert outcome is not None and outcome.status == "refused", f"a cancelled entry was reported as {outcome}"
    assert states(w4) == ["cancelled"]
    no_send(w4)


# -- 4. the policy_id check is exact ---------------------------------------------------------------------------------


class AlwaysEqual(str):
    """A str subclass that vouches for itself: equal to anything, so `ref != d.policy_id` is False."""  # noqa: D400

    def __eq__(self, other: object) -> bool:
        return True

    def __ne__(self, other: object) -> bool:
        return False

    __hash__ = str.__hash__


class PlainSubclass(str):
    pass


def stamp(clock: Any, ref: Any = POLICY_ID) -> dict:
    return {"by": "policy", "ref": ref, "at": iso(clock())}


IMPOSTORS = {
    "str_subclass_equal_to_anything": lambda c: decision(c, policy_id=AlwaysEqual("pol_other_owner"), authz=stamp(c)),
    "str_subclass_same_text": lambda c: decision(c, policy_id=PlainSubclass(POLICY_ID), authz=stamp(c)),
    "str_subclass_on_both": lambda c: decision(
        c, policy_id=PlainSubclass(POLICY_ID), authz=stamp(c, PlainSubclass(POLICY_ID))
    ),
    "bool": lambda c: decision(c, policy_id=True, authz=stamp(c, True)),
    "int": lambda c: decision(c, policy_id=1, authz=stamp(c, 1)),
    "none": lambda c: decision(c, policy_id=None, authz=stamp(c, None)),
}


@pytest.mark.parametrize("case", sorted(IMPOSTORS))
def test_FR_CHN_11_wire4_a_policy_id_that_is_not_an_exact_str_fails_closed_to_l1(case: str) -> None:
    w4 = make_w4()
    w4.policy.respond = lambda user_id, proposal: IMPOSTORS[case](w4.clock)
    ctx, result = w4.pair(w4.thread())

    card = w4.ap.preview(USER, ctx, result)

    assert card.level == "L1" and card.scheduled_at is None and w4.entries() == []
    assert w4.ap.policy_applied(USER, card.card_id) is None and w4.of_type("policy.applied") == []
    assert w4.new_ap().send(USER, card.card_id).status == "refused"
    no_send(w4)


def test_FR_CHN_11_wire4_an_exact_str_policy_id_still_rides_l2() -> None:
    """Guard against over-tightening: the clean decision of the fake engine still schedules the L2 entry."""
    w4 = make_w4()
    ctx, result = w4.pair(w4.thread())

    card = w4.ap.preview(USER, ctx, result)

    (entry,) = w4.entries()
    assert card.level == "L2" and entry["authz"]["ref"] == POLICY_ID and type(entry["authz"]["ref"]) is str
    assert w4.ap.policy_applied(USER, card.card_id)["data"]["policy_id"] == POLICY_ID
