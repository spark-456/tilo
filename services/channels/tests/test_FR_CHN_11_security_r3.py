"""FR-CHN-11 security round 3 (PR #249): the enqueue / stop protocol of `tilo_channels.autopilot_state` under
interleavings and crashes. PRD 11.6: "L2 send can be cancelled within 60 s; no send after cancel". If any Cancel
answered "cancelled" (or an Edit of the L2 card returned a redraft), no entry of the card is ever sent; "too_late" only
when the outbox showed the entry sent; anything unconfirmed raises CancelPending. Fake clock and outbox; no real
send."""

from __future__ import annotations

import itertools

import pytest
from _chn11_lib import BENIGN, USER, autopilot_module, make_bench, needs_autopilot, pair, scripted_thread
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


class Down(Exception):
    """The outbox is unavailable (or its answer was lost)."""


class Crash(Exception):
    """The instance dies here."""


class Rig:
    """One L2 card over the pinned fakes, with one-shot faults on the outbox and the card store. A fault is consumed
    by the first call it matches, in order: ("enqueue", "down" | "lost" | "crash"), ("enqueue", "before" | "after",
    op[, "crash"]) runs another owner's op while the enqueue is in flight (then dies after the store), ("cancel",
    "down" | "lost"), ("create", slot,
    "before" | "after") and ("put", "before" | "after") crash around a card-store write."""

    def __init__(self) -> None:
        self.bench = make_bench("L2")
        self.ctx, self.result = pair(scripted_thread(self.bench), BENIGN)
        self.card_id = autopilot_module()._card_id(USER, self.ctx.instruction_id)
        self.faults: list[tuple] = []
        self.answers: list[str] = []  # every Cancel or Edit outcome, nested ones included
        self.confirmed = False  # a Cancel answered "cancelled" or an Edit returned a redraft
        self._ids = itertools.count()
        outbox, cards = self.bench.outbox, self.bench.cards
        real_enqueue, real_cancel, real_create, real_put = outbox.enqueue, outbox.cancel, cards.create, cards.put

        def enqueue(entry, evidence):
            fault = self._take("enqueue")
            if fault == ("enqueue", "down"):
                raise Down("outbox unavailable")
            if fault and fault[1] == "before":
                self.act(fault[2])
            stored = real_enqueue(entry, evidence)
            if fault and fault[1] == "after":
                self.act(fault[2])
            if fault == ("enqueue", "lost"):
                raise Down("stored, answer lost")
            if fault and (fault == ("enqueue", "crash") or fault[-1] == "crash"):
                raise Crash("died after the outbox stored the entry")
            return stored

        def cancel(outbox_id):
            fault = self._take("cancel")
            if fault == ("cancel", "down"):
                raise Down("outbox unavailable")
            done = real_cancel(outbox_id)
            if fault == ("cancel", "lost"):
                raise Down("cancelled, answer lost")
            return done

        def create(user_id, key, value):
            fault = self._take("create", key)
            if fault and fault[2] == "before":
                raise Crash(f"died before writing {key}")
            stored = real_create(user_id, key, value)
            if fault:
                raise Crash(f"died after writing {key}")
            return stored

        def put(user_id, key, value):
            fault = self._take("put")
            if fault == ("put", "before"):
                raise Crash("died before the card write")
            real_put(user_id, key, value)
            if fault:
                raise Crash("died after the card write")

        outbox.enqueue, outbox.cancel, cards.create, cards.put = enqueue, cancel, create, put

    def _take(self, kind: str, key: str = "") -> tuple | None:
        for i, fault in enumerate(self.faults):
            slot_ok = kind != "create" or key.endswith(fault[1]) or (fault[1] == "card" and "#" not in key)
            if fault[0] == kind and slot_ok:
                return self.faults.pop(i)
        return None

    def act(self, op: str) -> None:
        """One owner action on the card; failures are what a caller would see (and could retry)."""
        ap = self.bench.new_autopilot()
        try:
            if op == "replay":
                ap.preview(USER, self.ctx, self.result)
            elif op == "send":
                ap.send(USER, self.card_id)
            elif op == "cancel":
                status = ap.cancel(USER, self.card_id).status
                self.answers.append(status)
                self.confirmed |= status == "cancelled"
            elif op == "edit":
                new = ap.edit(USER, self.card_id, "add a thank you", instruction_id=f"ins-r3-{next(self._ids)}")
                self.answers.append("edited" if new is not None else "none")
                self.confirmed |= new is not None
            elif op == "advance":
                self.bench.rig.clock.advance(25)
            elif op == "dispatch":
                self.bench.outbox.dispatch_due()
        except (Down, Crash, autopilot_module().CancelPending) as exc:
            self.answers.append(type(exc).__name__)

    def check(self) -> None:
        """Advances past every scheduled_at, dispatches, and checks PRD 11.6."""
        self.faults.clear()
        self.bench.rig.clock.advance(3600)
        self.bench.outbox.dispatch_due()
        policy = [e for e in self.bench.outbox.all() if e["authz"]["by"] == "policy"]
        assert len(policy) <= 1, "one card, one entry"
        sent = [e for e in policy if e["state"] == "sent"]
        if self.confirmed:
            assert sent == [], f"sent after a confirmed stop: {self.answers}"
        if "too_late" in self.answers:
            assert sent, "too_late although nothing was sent"


def started(first_fault: tuple | None = ("enqueue", "down")) -> Rig:
    rig = Rig()
    rig.faults = [first_fault] if first_fault else []
    rig.act("replay")
    rig.faults.clear()
    rig.answers.clear()
    return rig


def test_FR_CHN_11_r3a_cancel_during_an_in_flight_enqueue_that_then_dies() -> None:
    rig = started()  # the card is recorded at L2; its first enqueue failed
    rig.faults = [("enqueue", "before", "cancel", "crash")]
    rig.act("replay")  # A's enqueue in flight; the owner's Cancel runs; A's entry is stored; A dies
    assert rig.answers[0] == "cancelled" and rig.confirmed
    assert all(e["state"] == "cancelled" for e in rig.bench.outbox.all())
    rig.check()


def test_FR_CHN_11_r3b_a_failed_recheck_cancel_raises_and_cancelled_is_never_said_early() -> None:
    rig = started()
    # A's enqueue in flight; the owner's Cancel finds nothing to cancel and cannot read the outbox; A stores; both
    # cancels of A's re-check fail.
    rig.faults = [("enqueue", "before", "cancel"), ("enqueue", "down")] + [("cancel", "down")] * 3
    rig.act("replay")
    assert rig.answers == ["CancelPending", "CancelPending"], "neither side may claim the cancel"
    (entry,) = rig.bench.outbox.all()
    assert entry["state"] == "scheduled"
    rig.act("cancel")  # the owner retries
    assert rig.answers[-1] == "cancelled" and entry["id"] and rig.bench.outbox.state(entry["id"]) == "cancelled"
    rig.check()


@pytest.mark.parametrize("cancel_faults", [[("cancel", "down"), ("enqueue", "down")], [("cancel", "down")] * 2])
def test_FR_CHN_11_r3c_enqueue_landed_answer_lost_then_cancel_unconfirmed_is_pending(cancel_faults) -> None:
    rig = started(("enqueue", "lost"))  # the entry is stored; the preview saw an error
    rig.faults = list(cancel_faults)
    rig.act("cancel")
    assert rig.answers == ["CancelPending"] and not rig.confirmed
    rig.act("cancel")
    assert rig.answers[-1] == "cancelled"
    rig.check()


def test_FR_CHN_11_r3_late_entry_cancel_at_70_s_is_pending_never_too_late() -> None:
    rig = started()  # t=0: the first enqueue failed
    rig.bench.rig.clock.advance(50)
    rig.act("replay")  # t=50: the entry is stored, scheduled_at t=110
    (entry,) = rig.bench.outbox.all()
    rig.bench.rig.clock.advance(20)  # t=70
    rig.faults = [("cancel", "down"), ("cancel", "down")]
    rig.act("cancel")
    assert rig.answers == ["CancelPending"], "inside the entry's own window an unconfirmed cancel is pending"
    assert rig.bench.outbox.state(entry["id"]) == "scheduled"
    rig.bench.rig.clock.advance(5)
    rig.act("cancel")
    assert rig.answers[-1] == "cancelled"
    rig.check()


def test_FR_CHN_11_r3_stop_with_no_enqueue_started_is_final() -> None:
    rig = Rig()
    rig.faults = [("create", "#enqueuing", "before")]  # the preview dies before its first slot write
    rig.act("replay")
    rig.act("cancel")
    assert rig.answers[-1] == "cancelled"
    rig.act("replay")
    rig.act("send")
    assert rig.bench.outbox.entries == {}, "no enqueue after a recorded stop"
    rig.check()


SLOTS = ["#enqueuing", "#stop", "#cancelled", "#decision", "card"]
FAULT = st.one_of(
    st.none(),
    st.sampled_from(
        [("enqueue", "down"), ("enqueue", "lost"), ("enqueue", "crash"), ("cancel", "down"), ("cancel", "lost")]
        + [("put", w) for w in ("before", "after")]
        + [("create", s, w) for s in SLOTS for w in ("before", "after")]
    ),
    st.tuples(
        st.just("enqueue"),
        st.sampled_from(["before", "after"]),
        st.sampled_from(["cancel", "edit", "replay", "send"]),
        st.sampled_from(["ok", "crash"]),
    ),
)
STEP = st.tuples(
    st.sampled_from(["replay", "send", "cancel", "edit", "advance", "dispatch"]), st.lists(FAULT, max_size=3)
)


@needs_autopilot
@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(first=st.lists(FAULT, max_size=2), steps=st.lists(STEP, min_size=1, max_size=10))
def test_FR_CHN_11_r3_no_send_after_a_confirmed_stop_under_crashes_and_interleavings(first, steps) -> None:
    rig = Rig()
    rig.faults = [f for f in first if f]
    rig.act("replay")
    for op, faults in steps:
        rig.faults = [f for f in faults if f]
        rig.act(op)
    rig.check()
