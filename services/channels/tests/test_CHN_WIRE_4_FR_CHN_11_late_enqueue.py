"""CHN-WIRE-4 (FR-CHN-11; issue #307 plan ticket 4 "late first enqueue"; PRD 10.4, 11.4 Undo, 11.6; OB-01, OB-02, OB-03;
CHN-GATE-A semantics): an L2 card's decision is stored when it is made. If the first enqueue happens within
`DECISION_MAX_AGE_S` of the decision's `authz.at` the entry carries that stored authz (never `now`); later than that,
or whenever the policy's answer is unknown, the engine is asked again with the stored proposal and the card drops to
L1 unless it still says `run_after_undo`: a send decided before a revocation stays covered, a late send after it never
is, and "Stop all autopilot" is never extended across. A stop recorded before the enqueue still wins (CHN-GATE-A).
`scheduled_at` is `created_at + undo_window_s`, so a late enqueue restarts the undo window. API: API_CHN_WIRE_4.md.
Fake engine, `FakeOutbox`, fake clock; no network, no real mail.
"""

from __future__ import annotations

import itertools
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from _channels_lib import T0
from _chn11_lib import POLICY_ID, USER, autopilot_module, parse_ts
from _chn13_lib import iso
from _chn_wire4_lib import (
    Revocable,
    assert_no_send_ever,
    attempt,
    card_id_of,
    decision,
    gate_decision,
    make_w4,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


def bound() -> int:
    return autopilot_module().DECISION_MAX_AGE_S


def pending(policy=None, **kw):
    """A card decided at T0 whose first enqueue failed (the outbox was down): the decision is stored, no entry."""
    w4 = make_w4(policy, **kw)
    ctx, result = w4.pair(w4.thread())
    w4.outbox.down = True
    attempt(lambda: w4.ap.preview(USER, ctx, result))
    card_id = card_id_of(ctx)
    stored = w4.ap.policy_applied(USER, card_id)
    assert stored is not None and w4.entries() == [], "setup: decided and stored, nothing enqueued yet"
    w4.outbox.down = False
    return w4, ctx, result, card_id, stored


def retry(w4, via: str, ctx, result, card_id):
    """The first enqueue that finally happens: a replay of the preview or the owner's Send (a restarted instance)."""
    ap = w4.new_ap()
    return attempt(lambda: ap.preview(USER, ctx, result) if via == "preview" else ap.send(USER, card_id))


VIA = pytest.mark.parametrize("via", ["preview", "send"])


def seconds(a: str, b: str) -> float:
    return (parse_ts(a) - parse_ts(b)).total_seconds()


def test_CHN_WIRE_4_FR_CHN_11_the_freshness_bound_is_a_small_pinned_number_of_seconds() -> None:
    value = bound()
    assert isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 60


@VIA
def test_CHN_WIRE_4_FR_CHN_11_a_first_enqueue_within_the_bound_carries_the_stored_authz_not_now(via: str) -> None:
    w4, ctx, result, card_id, stored = pending()
    w4.clock.advance(bound() - 1)

    retry(w4, via, ctx, result, card_id)

    (entry,) = w4.entries()
    assert len(w4.policy.calls) == 1, "inside the bound the stored decision is used: the policy is not asked again"
    assert entry["authz"] == stored["authz"] and entry["authz"]["at"] == iso(T0)
    assert entry["created_at"] == iso(T0 + bound() - 1) != entry["authz"]["at"], "created_at is the enqueue time"
    assert seconds(entry["scheduled_at"], entry["created_at"]) == entry["undo_window_s"] == 60
    assert w4.ap.policy_applied(USER, card_id) == stored and len(w4.of_type("policy.applied")) == 1


@VIA
def test_CHN_WIRE_4_FR_CHN_11_a_late_first_enqueue_is_decided_again_and_runs_only_on_the_new_decision(via: str) -> None:
    """Later than the bound the engine is asked again with the stored proposal; if it still says run_after_undo the
    entry carries THAT decision's authz (stored, emitted), never the old one and never a re-stamp."""
    w4, ctx, result, card_id, stored = pending()
    w4.clock.advance(bound() + 1)

    retry(w4, via, ctx, result, card_id)

    assert len(w4.policy.calls) == 2 and w4.policy.proposals()[1] == w4.policy.proposals()[0], "the stored data"
    (entry,) = w4.entries()
    now_part = w4.ap.policy_applied(USER, card_id)
    assert entry["authz"] == now_part["authz"] and entry["authz"]["at"] == iso(T0 + bound() + 1)
    assert now_part["data"]["outbox_id"] == entry["id"] == stored["data"]["outbox_id"]
    assert now_part in w4.of_type("policy.applied"), "HR-7: the entry's authz is a recorded event's"
    assert seconds(entry["scheduled_at"], entry["created_at"]) == entry["undo_window_s"], "a late enqueue restarts it"


@VIA
def test_CHN_WIRE_4_FR_CHN_11_a_late_send_after_a_revocation_drops_to_l1_and_never_sends(via: str) -> None:
    """The policy was revoked (or "Stop all autopilot") after the decision: the late enqueue is not covered. The card
    is L1, waits for its owner, writes no entry and sends nothing, however long the clock runs."""
    w4, ctx, result, card_id, stored = pending(Revocable)
    w4.policy.revoked = True
    w4.clock.advance(bound() + 1)

    first = retry(w4, via, ctx, result, card_id)
    second = retry(w4, "preview", ctx, result, card_id)

    assert w4.entries() == []
    assert getattr(first, "level", "L1") == "L1" and second is not None and second.level == "L1"
    assert (second.undo_window_s, second.scheduled_at) == (0, None)
    assert w4.ap.policy_applied(USER, card_id) is None, "a dropped card holds no live decision"
    requested = w4.ap.approval_requested(USER, card_id)
    assert requested is not None and requested["data"]["outbox_id"] == second.outbox_id == stored["data"]["outbox_id"]
    assert w4.of_type("approval.requested") == [requested], "the gate is raised once, by whoever dropped the card"
    assert w4.new_ap().send(USER, card_id).status == "refused", "an L1 card needs the owner's approval"
    assert_no_send_ever(w4)


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(lambda c: (_ for _ in ()).throw(RuntimeError("policy store unavailable")), id="lookup_raises"),
        pytest.param(lambda c: None, id="unknown_none"),
        pytest.param(lambda c: gate_decision(), id="gate"),
        pytest.param(lambda c: decision(c, authz={"by": "person", "ref": USER, "at": iso(c())}), id="authz_by_person"),
        pytest.param(lambda c: decision(c, undo_window_s=0), id="window_zero"),
    ],
)
def test_CHN_WIRE_4_FR_CHN_11_a_late_enqueue_with_unknown_or_unusable_policy_state_drops_to_l1(answer: Any) -> None:
    w4, ctx, result, card_id, stored = pending()
    w4.policy.respond = lambda user_id, proposal: answer(w4.clock)
    w4.clock.advance(bound() + 1)

    card = retry(w4, "preview", ctx, result, card_id)

    assert w4.entries() == [] and card is not None and card.level == "L1"
    assert len(w4.policy.calls) == 2
    assert w4.new_ap().send(USER, card_id).status == "refused"
    assert_no_send_ever(w4)


@VIA
def test_CHN_WIRE_4_FR_CHN_11_a_replay_long_after_the_entry_was_stored_changes_nothing(via: str) -> None:
    """The freshness bound is for the first enqueue only: once the card's entry exists (even a sent one), a replay or a
    Send any time later asks nothing, adds nothing and leaves the card L2 (OB-03)."""
    w4 = make_w4()
    ctx, result = w4.pair(w4.thread())
    card = w4.ap.preview(USER, ctx, result)
    (entry,) = w4.entries()
    w4.clock.advance(10 * bound() + 60)
    w4.outbox.dispatch_due()

    again = retry(w4, via, ctx, result, card.card_id)

    assert [e["id"] for e in w4.entries()] == [entry["id"]]
    assert len(w4.policy.calls) == 1 and len(w4.of_type("policy.applied")) == 1
    assert getattr(again, "level", "L2") == "L2" and w4.of_type("approval.requested") == []
    assert w4.ap.policy_applied(USER, card.card_id)["authz"] == entry["authz"]
    assert len(w4.outbox.sent) == 1


def test_CHN_WIRE_4_FR_CHN_11_a_dropped_card_is_replayed_without_asking_again_or_raising_a_second_gate() -> None:
    w4, ctx, result, card_id, _ = pending(Revocable)
    w4.policy.revoked = True
    w4.clock.advance(bound() + 1)
    retry(w4, "preview", ctx, result, card_id)
    calls = len(w4.policy.calls)

    for _ in range(3):
        card = w4.new_ap().preview(USER, ctx, result)
        w4.new_ap().send(USER, card_id)
        assert card.level == "L1"

    assert len(w4.policy.calls) == calls and len(w4.of_type("approval.requested")) == 1 and w4.entries() == []


@VIA
def test_CHN_WIRE_4_FR_CHN_11_a_cancel_recorded_before_the_late_enqueue_still_wins(via: str) -> None:
    """CHN-GATE-A unchanged: the owner's Cancel after the decision and before any enqueue means no entry, ever."""
    w4, ctx, result, card_id, _ = pending()
    assert w4.ap.cancel(USER, card_id).status == "cancelled"
    w4.clock.advance(bound() + 1)

    retry(w4, via, ctx, result, card_id)

    assert w4.entries() == [] and w4.ap.stop_state(USER, card_id) == "cancelled"
    assert w4.new_ap().send(USER, card_id).status == "refused"
    assert_no_send_ever(w4)


def stamped_apart(w4) -> None:
    """Each decide call stamps a different `authz.at` (now minus 0, 1, 2 ... s), so a mix-up between decisions shows."""
    counter = itertools.count()
    w4.policy.respond = lambda user_id, proposal: decision(
        w4.clock, authz={"by": "policy", "ref": POLICY_ID, "at": iso(w4.clock() - next(counter) % 5)}
    )


def test_CHN_WIRE_4_FR_CHN_11_racing_instances_agree_on_one_stored_decision_one_entry_one_event() -> None:
    """Eight instances preview the same new card at once: one create wins; the entry carries exactly the stored
    decision's authz; one policy.applied is emitted (by the create winner); one entry exists."""
    w4 = make_w4()
    stamped_apart(w4)
    ctx, result = w4.pair(w4.thread())
    card_id = card_id_of(ctx)
    gate = threading.Barrier(8)

    def run(_: int) -> Any:
        ap = w4.new_ap()
        gate.wait()
        return attempt(lambda: ap.preview(USER, ctx, result))

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(run, range(8)))

    (entry,) = w4.entries()
    stored = w4.ap.policy_applied(USER, card_id)
    assert entry["authz"] == stored["authz"], "the entry is stamped from the stored decision, whoever enqueued it"
    assert w4.of_type("policy.applied") == [stored]


def test_CHN_WIRE_4_FR_CHN_11_racing_late_replays_leave_one_decision_and_one_entry_stamped_from_it() -> None:
    w4, ctx, result, card_id, _ = pending()
    stamped_apart(w4)
    w4.clock.advance(bound() + 1)
    gate = threading.Barrier(6)

    def run(_: int) -> Any:
        ap = w4.new_ap()
        gate.wait()
        return attempt(lambda: ap.preview(USER, ctx, result))

    with ThreadPoolExecutor(6) as pool:
        list(pool.map(run, range(6)))

    (entry,) = w4.entries()
    stored = w4.ap.policy_applied(USER, card_id)
    assert entry["authz"] == stored["authz"], "one decision wins; the entry never carries a losing one"
    assert stored in w4.of_type("policy.applied")


OPS = st.lists(
    st.one_of(
        st.tuples(st.just("advance"), st.sampled_from([1, 10, 30, 59, 61, 120, 600])),
        st.sampled_from([("revoke", 0), ("down", 0), ("up", 0), ("replay", 0), ("send", 0), ("cancel", 0)]),
    ),
    max_size=14,
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(start_down=st.booleans(), ops=OPS)
def test_CHN_WIRE_4_FR_CHN_11_property_no_authorisation_outlives_the_bound_a_revocation_or_a_stop(
    start_down: bool, ops: list[tuple[str, int]]
) -> None:
    """Random replays, Sends, Cancels, revocations, outage and time: at most one entry; an entry's authz is the
    policy's, no later than the revocation, and no older than the bound when the entry was created; no entry appears
    after a
    Cancel, nor from a card that dropped to L1."""
    w4 = make_w4(Revocable)
    ctx, result = w4.pair(w4.thread())
    card_id = card_id_of(ctx)
    w4.outbox.down = start_down
    attempt(lambda: w4.ap.preview(USER, ctx, result))
    revoked_at: float | None = None
    stopped, dropped = False, False
    known: set[str] = {e["id"] for e in w4.entries()}

    for op, n in ops:
        ap = w4.new_ap()
        if op == "advance":
            w4.clock.advance(n)
        elif op == "revoke":
            w4.policy.revoked, revoked_at = True, revoked_at if revoked_at is not None else w4.clock()
        elif op in ("down", "up"):
            w4.outbox.down = op == "down"
        elif op == "replay":
            card = attempt(lambda: ap.preview(USER, ctx, result))
            dropped = dropped or (card is not None and card.level == "L1")
        elif op == "send":
            attempt(lambda: ap.send(USER, card_id))
        elif op == "cancel":
            stopped = True  # recorded before the outbox is first called (CHN-GATE-A), answered or not
            attempt(lambda: ap.cancel(USER, card_id))

        entries = w4.entries()
        assert len(entries) <= 1
        for entry in entries:
            if entry["id"] not in known:
                assert not stopped, "no entry may start after a Cancel"
                assert not dropped, "a card that dropped to L1 never enqueues without a person's approval"
                known.add(entry["id"])
            assert entry["authz"]["by"] == "policy" and entry["authz"]["ref"] == POLICY_ID
            age = seconds(entry["created_at"], entry["authz"]["at"])
            assert 0 <= age <= bound(), "an authorisation older than the bound is never used"
            if revoked_at is not None:
                assert parse_ts(entry["authz"]["at"]).timestamp() <= revoked_at, "nothing is stamped after a revocation"
