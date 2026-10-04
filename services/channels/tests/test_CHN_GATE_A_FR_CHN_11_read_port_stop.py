"""CHN-GATE-A gate 1 (issue #256; gates FR-CHN-11, PRD 11.6 "L2 send can be cancelled within 60 s; no send after
cancel"): a stop never creates an outbox entry. The stop side reads the entry through the outbox read port
(`get`, `get_by_idempotency_key`) and revokes the card's key (`revoke`); it never calls `enqueue`. Today it looks the
entry up by enqueueing the card's key again, so a Cancel tap on a card whose entry was never stored creates one, and
if the cancel of that entry then fails and nobody retries, the Cancel itself creates a mail sent at 60 s.

API pinned in API_CHN_GATE_A.md (BQ-186). Fake clock, fake outbox; no real send, no network.
"""

from __future__ import annotations

import pytest
from _chn11_lib import needs_autopilot
from _chn_gate_a_lib import USER, OutboxDown, Rig, autopilot_module, make_gate
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ALL = {"enqueue", "cancel", "revoke", "get", "get_by_idempotency_key"}
# what the outbox does while the stop runs: (down, lost)
OUTBOX_AT_STOP = {
    "healthy": (set(), set()),
    "cancel_down": ({"cancel"}, set()),
    "cancel_and_revoke_down": ({"cancel", "revoke"}, set()),
    "reads_and_cancel_down": ({"cancel", "get", "get_by_idempotency_key"}, set()),
    "everything_down": (ALL, set()),
    "answers_lost": (set(), {"cancel", "revoke"}),
}


def stop(ap, op: str, card_id: str, n: int = 0) -> str:
    """Runs a Cancel or an Edit of the card; returns its answer, "CancelPending" when it raised that."""
    try:
        if op == "cancel":
            return ap.cancel(USER, card_id).status
        new = ap.edit(USER, card_id, "add a thank you", instruction_id=f"ins-gate-a-edit-{n}")
        return "cancelled" if new is not None else "none"
    except autopilot_module().CancelPending:
        return "CancelPending"


def never_enqueued_card(gate):
    """An L2 card recorded by a preview whose enqueue never reached the outbox (it was down)."""
    ctx, result, card_id = gate.new_card()
    gate.outbox.down = {"enqueue"}
    with pytest.raises(OutboxDown):
        gate.autopilot(sweeper=False).preview(USER, ctx, result)
    gate.outbox.heal()
    assert gate.outbox.entries == {}, "test setup: the preview stored nothing"
    return ctx, result, card_id


@pytest.mark.parametrize("outbox_state", list(OUTBOX_AT_STOP))
@pytest.mark.parametrize("op", ["cancel", "edit"])
def test_CHN_GATE_A_FR_CHN_11_stop_on_never_enqueued_card_creates_no_entry(op: str, outbox_state: str) -> None:
    gate = make_gate("L2")
    _, _, card_id = never_enqueued_card(gate)
    gate.outbox.down, gate.outbox.lost = (set(s) for s in OUTBOX_AT_STOP[outbox_state])
    calls = gate.outbox.port_calls["enqueue"]
    answer = stop(gate.autopilot(sweeper=False), op, card_id)
    assert gate.outbox.port_calls["enqueue"] == calls, f"the {op} called Outbox.enqueue (it may only read or revoke)"
    assert gate.outbox.entries == {}, f"the {op} tap created an outbox entry"
    if outbox_state == "healthy":
        assert answer == "cancelled", "BQ-186: with a healthy outbox the revoked key is final"
    else:
        assert answer in ("cancelled", "CancelPending"), answer


@pytest.mark.parametrize("outbox_state", [s for s in OUTBOX_AT_STOP if s not in ("healthy", "everything_down")])
def test_CHN_GATE_A_FR_CHN_11_failed_cancel_tap_never_becomes_a_mail_sent_at_60_s(outbox_state: str) -> None:
    """Issue #256: the Cancel's cancel fails and nobody retries; nothing may be sent at 60 s or ever after."""
    gate = make_gate("L2")
    _, _, card_id = never_enqueued_card(gate)
    gate.outbox.down, gate.outbox.lost = (set(s) for s in OUTBOX_AT_STOP[outbox_state])
    stop(gate.autopilot(sweeper=False), "cancel", card_id)
    gate.outbox.heal()  # nobody retries the Cancel
    for seconds in (59, 1, 1, 3600):
        gate.clock.advance(seconds)
        gate.outbox.dispatch_due()
    assert gate.outbox.sent == [], "the Cancel tap created a mail that was sent"
    assert gate.outbox.entries == {}


@pytest.mark.parametrize("later", ["replay", "send", "replay_then_send"])
def test_CHN_GATE_A_FR_CHN_11_no_enqueue_after_a_recorded_stop_stores_an_entry(later: str) -> None:
    gate = make_gate("L2")
    ctx, result, card_id = never_enqueued_card(gate)
    gate.outbox.down = set(ALL)
    assert stop(gate.autopilot(sweeper=False), "cancel", card_id) == "CancelPending"  # recorded, not confirmed
    gate.outbox.heal()
    if later.startswith("replay"):
        try:
            gate.autopilot(sweeper=False).preview(USER, ctx, result)
        except autopilot_module().CancelPending:
            pass
    if later.endswith("send"):
        try:
            assert gate.autopilot(sweeper=False).send(USER, card_id).status == "refused"
        except autopilot_module().CancelPending:
            pass
    assert gate.outbox.entries == {}, "a later replay or Send stored an entry for a stopped card"
    assert gate.run_out() == []


@pytest.mark.parametrize(
    "faults",
    [
        {"down": {"cancel"}},
        {"lost": {"cancel"}},
        {"down": {"cancel", "revoke"}},
        {"down": {"cancel", "get", "get_by_idempotency_key"}},
    ],
    ids=["cancel_down", "cancel_lost", "cancel_revoke_down", "cancel_reads_down"],
)
@pytest.mark.parametrize("op", ["cancel", "edit"])
def test_CHN_GATE_A_FR_CHN_11_stop_of_a_stored_entry_never_calls_enqueue(op: str, faults: dict) -> None:
    gate = make_gate("L2")
    ctx, result, card_id = gate.new_card()
    preview = gate.autopilot(sweeper=False).preview(USER, ctx, result)
    assert preview.level == "L2" and len(gate.outbox.entries) == 1, "test setup: one scheduled L2 entry"
    gate.clock.advance(10)
    gate.outbox.down, gate.outbox.lost = set(faults.get("down", ())), set(faults.get("lost", ()))
    calls = gate.outbox.port_calls["enqueue"]
    answer = stop(gate.autopilot(sweeper=False), op, card_id)
    assert gate.outbox.port_calls["enqueue"] == calls, f"the {op} called Outbox.enqueue"
    assert answer in ("cancelled", "CancelPending")
    if answer == "cancelled":
        assert gate.outbox.state(preview.outbox_id) == "cancelled", "cancelled said before the outbox confirmed"
    gate.outbox.heal()
    assert stop(gate.autopilot(sweeper=False), op, card_id) == "cancelled"  # the owner retries (the same Edit resumes)
    assert gate.outbox.state(preview.outbox_id) == "cancelled"
    assert gate.outbox.port_calls["enqueue"] == calls
    assert gate.run_out() == []


@pytest.mark.parametrize("enqueuer", ["ok", "crash"])
@pytest.mark.parametrize("op", ["cancel", "edit"])
def test_CHN_GATE_A_FR_CHN_11_stop_racing_the_first_enqueue_before_it_stores(op: str, enqueuer: str) -> None:
    """The owner's Cancel or Edit lands while the preview's enqueue is in flight, before the outbox stores the entry;
    the enqueuing instance then lives or dies. The stop never enqueues, says "cancelled", and nothing is ever sent."""
    rig = Rig(sweeper=False)
    rig.faults = [("enqueue", "before", op, enqueuer)]
    rig.act("replay")
    assert rig.answers[0] in ("cancelled", "edited"), rig.answers
    assert rig.violations == [], rig.violations
    assert all(e["state"] == "cancelled" for e in rig.gate.outbox.all())
    rig.check()


@pytest.mark.parametrize(
    "down",
    [("cancel", "revoke"), ("cancel", "revoke", "get", "get_by_idempotency_key")],
    ids=["writes_down", "writes_and_reads_down"],
)
def test_CHN_GATE_A_FR_CHN_11_stop_racing_an_enqueue_the_outbox_cannot_confirm_is_pending(down: tuple) -> None:
    """Same race, but the outbox cannot confirm the stop (its cancel and revoke calls fail, a few times each):
    CancelPending, never "cancelled", and the stop never enqueues."""
    rig = Rig(sweeper=False)
    rig.faults = [("enqueue", "before", "cancel", "ok")] + [(call, "down") for call in down for _ in range(4)]
    rig.act("replay")
    assert rig.answers[0] == "CancelPending", rig.answers
    assert rig.violations == [], rig.violations
    assert len(rig.gate.outbox.entries) <= 1
    rig.check()


# -- property: any interleaving, any fault, no stop creates an entry ---------------------------------------------

CALLS = ["cancel", "revoke", "get", "get_by_idempotency_key"]
FAULT = st.one_of(
    st.none(),
    st.sampled_from(
        [("enqueue", "down"), ("enqueue", "lost"), ("enqueue", "crash")]
        + [(c, w) for c in CALLS for w in ("down", "lost")]
        + [(k, w) for k in ("create", "put") for w in ("crash_before", "crash_after")]
    ),
    st.tuples(
        st.just("enqueue"),
        st.sampled_from(["before", "after"]),
        st.sampled_from(["cancel", "edit", "replay", "send"]),
        st.sampled_from(["ok", "crash"]),
    ),
)
CRASH = st.one_of(st.none(), st.tuples(st.integers(1, 5), st.sampled_from(["before", "after"])))
STEP = st.tuples(
    st.sampled_from(["replay", "send", "cancel", "edit", "advance", "dispatch"]),
    st.lists(FAULT, max_size=3),
    CRASH,
)


@needs_autopilot
@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(first=st.lists(FAULT, max_size=2), steps=st.lists(STEP, min_size=1, max_size=10))
def test_CHN_GATE_A_FR_CHN_11_no_stop_creates_an_entry_under_any_interleaving(first, steps) -> None:
    rig = Rig(sweeper=False)
    rig.start([f for f in first if f])
    for op, faults, crash in steps:
        rig.faults = [f for f in faults if f]
        rig.crash_at = (op, crash[0], crash[1]) if crash and op in ("replay", "send", "cancel", "edit") else None
        rig._counted = 0
        rig.act(op)
        rig.crash_at = None
    rig.check()
