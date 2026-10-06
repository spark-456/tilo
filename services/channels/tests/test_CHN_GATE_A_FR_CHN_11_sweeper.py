"""CHN-GATE-A gate 2 (issue #256; gates FR-CHN-11, PRD 11.4 Undo "Cancel works until then", PRD 11.6 "no send after
cancel"; BQ-170): a sweeper settles every stop the outbox did not confirm (`CancelPending`) before the entry's
`scheduled_at`, from any instance and after a restart, and surfaces can show "not confirmed, retry" through
`Autopilot.stop_state`. A sweep never creates an entry, never touches a card without a stop, and never says
"cancelled" for an entry that was sent.

API pinned in API_CHN_GATE_A.md (BQ-187, BQ-188). Fake clock, fake outbox; no real send, no network.
"""

from __future__ import annotations

import threading
import time

import pytest
from _chn11_lib import at, needs_autopilot, parse_ts
from _chn_gate_a_lib import PORT, USER, Rig, autopilot_module, make_gate, needs_sweeper
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

STOP_SIDE = {"cancel", "revoke"}  # the outbox calls that can confirm a stop


def pending_stop(gate, *, stored: bool = True, after_s: float = 10) -> tuple[str, str | None]:
    """A card whose Cancel the outbox could not confirm (CancelPending); the outbox is healthy again afterwards.
    Returns (card_id, outbox_id); outbox_id is None when the preview never stored the entry."""
    ctx, result, card_id = gate.new_card()
    ap = gate.autopilot()
    outbox_id = None
    if stored:
        outbox_id = ap.preview(USER, ctx, result).outbox_id
        assert gate.outbox.state(outbox_id) == "scheduled", "test setup: a scheduled L2 entry"
    else:
        gate.outbox.down = {"enqueue"}
        with pytest.raises(Exception):  # noqa: B017 - the outbox's own error
            ap.preview(USER, ctx, result)
    gate.clock.advance(after_s)
    gate.outbox.down = set(STOP_SIDE)
    with pytest.raises(autopilot_module().CancelPending):
        gate.autopilot().cancel(USER, card_id)
    gate.outbox.heal()
    return card_id, outbox_id


def test_CHN_GATE_A_FR_CHN_11_sweep_interval_leaves_several_tries_inside_the_undo_window() -> None:
    mod = autopilot_module()
    assert 0 < mod.SWEEP_INTERVAL_S <= mod.UNDO_WINDOW_S / 4, "BQ-187: at least four sweeps inside the 60 s window"


def test_CHN_GATE_A_FR_CHN_11_unconfirmed_cancel_is_pending_until_a_sweep_settles_it() -> None:
    gate = make_gate("L2")
    card_id, outbox_id = pending_stop(gate)  # t = 10 s
    assert gate.autopilot().stop_state(USER, card_id) == "pending", "surfaces show 'not confirmed, retry'"
    assert (USER, card_id) in gate.stops.pending()
    assert gate.outbox.state(outbox_id) == "scheduled"
    gate.clock.advance(10)  # t = 20 s, well before scheduled_at (60 s)
    calls = gate.outbox.port_calls["enqueue"]
    assert gate.autopilot().sweep() == {(USER, card_id): "cancelled"}  # another instance
    assert gate.outbox.port_calls["enqueue"] == calls, "a sweep never enqueues"
    assert gate.outbox.state(outbox_id) == "cancelled"
    assert gate.autopilot().stop_state(USER, card_id) == "cancelled"
    assert gate.stops.pending() == []
    assert gate.autopilot().cancel(USER, card_id).status == "cancelled"
    assert gate.autopilot().sweep() == {}, "nothing left to settle"
    assert gate.run_out() == []


def test_CHN_GATE_A_FR_CHN_11_sweeps_stay_pending_while_the_outbox_is_down_then_settle_before_scheduled_at() -> None:
    gate = make_gate("L2")
    card_id, outbox_id = pending_stop(gate, after_s=5)  # t = 5 s
    for _ in range(3):  # t = 15, 25, 35 s
        gate.clock.advance(10)
        gate.outbox.down = set(STOP_SIDE)
        assert gate.autopilot().sweep() == {(USER, card_id): "pending"}, "a failed settle is never raised"
        assert gate.autopilot().stop_state(USER, card_id) == "pending"
        gate.outbox.dispatch_due()
    gate.outbox.heal()
    gate.clock.advance(20)  # t = 55 s: the first healthy sweep, still inside the window
    assert gate.autopilot().sweep() == {(USER, card_id): "cancelled"}
    assert gate.outbox.state(outbox_id) == "cancelled"
    assert gate.run_out() == []


def test_CHN_GATE_A_FR_CHN_11_sweep_after_the_send_says_too_late_never_cancelled() -> None:
    gate = make_gate("L2")
    card_id, outbox_id = pending_stop(gate)  # t = 10 s
    gate.outbox.down = set(STOP_SIDE)
    gate.clock.advance(40)  # t = 50 s
    assert gate.autopilot().sweep() == {(USER, card_id): "pending"}
    gate.clock.advance(10)  # t = 60 s: due; the dispatcher still works
    gate.outbox.dispatch_due()
    assert gate.outbox.state(outbox_id) == "sent", "test setup: the entry went out"
    gate.outbox.heal()
    gate.clock.advance(10)
    assert gate.autopilot().sweep() == {(USER, card_id): "too_late"}
    assert gate.autopilot().stop_state(USER, card_id) == "too_late"
    assert gate.stops.pending() == []
    assert gate.autopilot().cancel(USER, card_id).status == "too_late"
    assert len(gate.outbox.sent) == 1


def test_CHN_GATE_A_FR_CHN_11_sweep_never_touches_a_card_without_a_stop() -> None:
    gate = make_gate("L2")
    stopped, stopped_id = pending_stop(gate, after_s=0)
    ctx, result, live = gate.new_card()
    live_id = gate.autopilot().preview(USER, ctx, result).outbox_id
    assert gate.autopilot().stop_state(USER, live) is None
    assert gate.autopilot().stop_state(USER, "apc_" + "0" * 32) is None
    gate.clock.advance(5)
    assert gate.autopilot().sweep() == {(USER, stopped): "cancelled"}
    assert gate.outbox.state(live_id) == "scheduled", "the sweep cancelled a card nobody stopped"
    assert gate.autopilot().stop_state(USER, live) is None
    gate.clock.advance(55)
    gate.outbox.dispatch_due()
    assert [oid for oid, _ in gate.outbox.sent] == [live_id], "the live card sends at 60 s exactly once"
    assert gate.outbox.state(stopped_id) == "cancelled"
    gate.run_out()
    assert len(gate.outbox.sent) == 1


def test_CHN_GATE_A_FR_CHN_11_sweep_never_creates_an_entry_for_a_never_enqueued_card() -> None:
    gate = make_gate("L2")
    card_id, _ = pending_stop(gate, stored=False)
    assert gate.outbox.entries == {}
    calls = gate.outbox.port_calls["enqueue"]
    assert gate.autopilot().sweep() == {(USER, card_id): "cancelled"}
    assert gate.outbox.port_calls["enqueue"] == calls, "a sweep never enqueues"
    assert gate.outbox.entries == {}
    assert gate.autopilot().stop_state(USER, card_id) == "cancelled"
    assert gate.run_out() == []
    assert gate.outbox.entries == {}


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("n", range(1, 9))
def test_CHN_GATE_A_FR_CHN_11_restart_cancel_instance_dies_at_any_call_then_a_sweep_settles(n: int, when: str) -> None:
    rig = Rig(sweeper=True, step_s=5)
    rig.start()
    assert len(rig.gate.outbox.entries) == 1, "test setup: one scheduled L2 entry"
    rig.act("advance")  # t = 5 s
    rig.crash_at, rig._counted = ("cancel", n, when), 0
    rig.act("cancel")
    rig.crash_at = None
    if rig.answers[-1] != "Died":
        assert rig.answers[-1] == "cancelled", "it finished before its n-th call"
    elif rig.died_on in PORT:
        assert rig.stop_state() is not None, "a stop is recorded before the outbox is first called"
    rig.act("advance")  # t = 10 s
    rig.act("sweep")  # a fresh instance, healthy outbox
    if rig.stop_state() is None:  # the stop was never recorded: the owner saw an error and taps again
        rig.act("cancel")
        assert rig.answers[-1] == "cancelled"
    assert rig.stop_state() == "cancelled", "a recorded stop the sweep did not settle"
    assert rig.gate.stops.pending() == []
    assert rig.check() == []


@pytest.mark.parametrize("when", ["before", "after"])
@pytest.mark.parametrize("n", range(1, 7))
def test_CHN_GATE_A_FR_CHN_11_restart_sweeper_dies_at_any_call_then_the_next_sweep_settles(n: int, when: str) -> None:
    rig = Rig(sweeper=True, step_s=5)
    rig.start()
    rig.act("advance")
    rig.gate.outbox.down = set(STOP_SIDE)
    rig.act("cancel")
    rig.gate.outbox.heal()
    assert rig.answers[-1] == "CancelPending" and rig.stop_state() == "pending"
    rig.crash_at, rig._counted = ("sweep", n, when), 0
    rig.act("sweep")
    rig.crash_at = None
    rig.act("advance")
    rig.act("sweep")
    assert rig.stop_state() == "cancelled"
    assert rig.gate.stops.pending() == []
    assert rig.check() == []


@pytest.mark.parametrize("with_cancel_taps", [False, True])
def test_CHN_GATE_A_FR_CHN_11_concurrent_sweepers_settle_each_card_once(with_cancel_taps: bool) -> None:
    gate = make_gate("L2")
    cards = [pending_stop(gate, after_s=1) for _ in range(5)]
    calls = gate.outbox.port_calls["enqueue"]
    real_cancel, real_revoke = gate.outbox.cancel, gate.outbox.revoke

    def slow(real):
        def call(*args):
            time.sleep(0.002)  # widens the window in which sweepers overlap
            return real(*args)

        return call

    gate.outbox.cancel, gate.outbox.revoke = slow(real_cancel), slow(real_revoke)
    workers = 4 + int(with_cancel_taps)
    barrier, results, errors, taps = threading.Barrier(workers), [], [], []

    def sweeper() -> None:
        ap = gate.autopilot()
        barrier.wait(timeout=10)
        try:
            results.append(ap.sweep())
        except BaseException as exc:  # noqa: BLE001 - every error is a failure here
            errors.append(repr(exc))

    def tapper() -> None:
        ap = gate.autopilot()
        barrier.wait(timeout=10)
        try:
            taps.extend(ap.cancel(USER, card_id).status for card_id, _ in cards)
        except BaseException as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=sweeper) for _ in range(4)]
    threads += [threading.Thread(target=tapper)] if with_cancel_taps else []
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert all(status == "cancelled" for result in results for status in result.values()), results
    assert all(status == "cancelled" for status in taps), taps
    for card_id, outbox_id in cards:
        assert gate.outbox.state(outbox_id) == "cancelled"
        assert gate.autopilot().stop_state(USER, card_id) == "cancelled"
    assert gate.stops.pending() == []
    assert gate.outbox.port_calls["enqueue"] == calls, "a sweep never enqueues"
    assert gate.run_out() == []


# -- property: one healthy sweep before scheduled_at settles every recorded stop ---------------------------------

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
        st.sampled_from(["cancel", "edit", "replay", "send", "sweep"]),
        st.sampled_from(["ok", "crash"]),
    ),
)
CRASH = st.one_of(st.none(), st.tuples(st.integers(1, 5), st.sampled_from(["before", "after"])))
STEP = st.tuples(
    st.sampled_from(["replay", "send", "cancel", "edit", "advance", "dispatch", "sweep"]),
    st.lists(FAULT, max_size=3),
    CRASH,
)


@needs_autopilot
@needs_sweeper
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(first=st.lists(FAULT, max_size=2), steps=st.lists(STEP, min_size=1, max_size=10))
def test_CHN_GATE_A_FR_CHN_11_one_healthy_sweep_before_scheduled_at_settles_every_recorded_stop(first, steps) -> None:
    rig = Rig(sweeper=True, step_s=5)  # ten steps move the clock at most 50 s: every entry is still in its window
    rig.start([f for f in first if f])
    for op, faults, crash in steps:
        rig.faults = [f for f in faults if f]
        rig.crash_at = (op, crash[0], crash[1]) if crash and op not in ("advance", "dispatch") else None
        rig._counted = 0
        rig.act(op)
        rig.crash_at = None
    rig.faults.clear()
    rig.gate.outbox.heal()
    now = at(rig.gate.clock)
    assert all(parse_ts(e["scheduled_at"]) > now for e in rig.gate.outbox.policy_entries())
    rig.act("sweep")  # a fresh instance after whatever died
    if rig.recorded:
        assert rig.stop_state() == "cancelled", f"a recorded stop is not settled: {rig.answers}"
    said = any(r.get((USER, rig.card_id)) == "cancelled" for r in rig.sweeps if "died" not in r)
    sent = rig.check()
    if rig.recorded or said:
        assert sent == [], f"sent after a recorded stop and a healthy sweep: {rig.answers}"
