"""FR-CHN-11 security round 2 (PR #249): a recorded Cancel or Edit of an L2 card stops every entry of that card (PRD
11.6 "L2 send can be cancelled within 60 s; no send after cancel"). Once a stop is recorded no path enqueues again,
an enqueue that raced the stop cancels its own entry, any Cancel cancels the entry whichever stop claim came first,
and a cancel the outbox did not confirm raises CancelPending instead of answering. Fake clock and outbox; no real
send."""

from __future__ import annotations

import pytest
from _chn11_lib import BENIGN, USER, autopilot_module, make_bench, needs_autopilot, pair, scripted_thread
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


class Down(Exception):
    pass


def flaky(bench):
    """Makes the outbox's enqueue and cancel raise while `state["down"]`; dispatch keeps running."""
    real_enqueue, real_cancel, state = bench.outbox.enqueue, bench.outbox.cancel, {"down": False}

    def enqueue(entry, evidence):
        if state["down"]:
            raise Down("outbox unavailable")
        return real_enqueue(entry, evidence)

    def cancel(outbox_id):
        if state["down"]:
            raise Down("outbox unavailable")
        return real_cancel(outbox_id)

    bench.outbox.enqueue, bench.outbox.cancel = enqueue, cancel
    return state


def card_id(ctx) -> str:
    return autopilot_module()._card_id(USER, ctx.instruction_id)


def never_sent(bench) -> None:
    for _ in range(3):
        bench.rig.clock.advance(600)
        bench.outbox.dispatch_due()
    assert bench.outbox.sent == [], "an entry was sent after Cancel or Edit succeeded"


@pytest.mark.parametrize("later", ["replay", "send", "both"])
@pytest.mark.parametrize("op", ["cancel", "edit"])
def test_FR_CHN_11_stop_while_the_outbox_is_down_then_replay_and_send_never_send(op: str, later: str) -> None:
    bench = make_bench("L2")
    state = flaky(bench)
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    state["down"] = True
    with pytest.raises(Down):
        bench.ap.preview(USER, ctx, result)  # the card is recorded at L2; its entry is not stored
    if op == "cancel":
        assert bench.ap.cancel(USER, card_id(ctx)).status == "cancelled"
    else:
        assert bench.ap.edit(USER, card_id(ctx), "add a thank you", instruction_id="ins-r2-edit") is not None
    state["down"] = False
    if later in ("replay", "both"):
        bench.new_autopilot().preview(USER, ctx, result)
    if later in ("send", "both"):
        assert bench.ap.send(USER, card_id(ctx)).status == "refused"
    assert bench.outbox.entries == {}, "no path enqueues once a stop is recorded"
    never_sent(bench)


def test_FR_CHN_11_cancel_the_outbox_cannot_confirm_raises_and_a_retry_completes_it() -> None:
    bench = make_bench("L2")
    state = flaky(bench)
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    card = bench.ap.preview(USER, ctx, result)
    bench.rig.clock.advance(10)
    state["down"] = True
    with pytest.raises(autopilot_module().CancelPending):
        bench.ap.cancel(USER, card.card_id)
    assert bench.ap.send(USER, card.card_id).status == "refused", "a stopped card never enqueues again"
    state["down"] = False
    bench.new_autopilot().preview(USER, ctx, result)  # any later touch completes the recorded stop
    assert bench.outbox.state(card.outbox_id) == "cancelled"
    assert bench.ap.cancel(USER, card.card_id).status == "cancelled"
    never_sent(bench)


@pytest.mark.parametrize("where", ["after_claim", "before_cancel"])
def test_FR_CHN_11_edit_dies_inside_its_stop_then_cancel_at_10_s_is_cancelled(where: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, BENIGN))
    real_create, real_cancel = bench.cards.create, bench.outbox.cancel

    def create(user_id, key, value):
        stored = real_create(user_id, key, value)
        if key.endswith("#stop"):
            raise RuntimeError("instance died after its stop claim")
        return stored

    def cancel(outbox_id):
        raise RuntimeError("instance died before the outbox cancel")

    if where == "after_claim":
        bench.cards.create = create
    else:
        bench.outbox.cancel = cancel
    with pytest.raises(RuntimeError):  # CancelPending is a RuntimeError too
        bench.ap.edit(USER, card.card_id, "add a thank you", instruction_id="ins-r2-dies")
    bench.cards.create, bench.outbox.cancel = real_create, real_cancel
    bench.rig.clock.advance(10)
    assert bench.ap.cancel(USER, card.card_id).status == "cancelled", "Cancel wins whoever claimed the stop"
    assert bench.outbox.state(card.outbox_id) == "cancelled"
    never_sent(bench)


@pytest.mark.parametrize("order", ["cancel_before_store", "cancel_after_store"])
@pytest.mark.parametrize("op", ["preview", "send"])
def test_FR_CHN_11_an_enqueue_racing_a_cancel_cancels_its_own_entry(op: str, order: str) -> None:
    bench = make_bench("L2")
    state = flaky(bench)
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    state["down"] = True
    with pytest.raises(Down):
        bench.ap.preview(USER, ctx, result)
    state["down"] = False
    other, real, answers = bench.new_autopilot(), bench.outbox.enqueue, []

    def enqueue(entry, evidence):  # the owner's Cancel lands while this enqueue is in flight
        if order == "cancel_before_store" and not answers:
            answers.append(other.cancel(USER, card_id(ctx)).status)
        stored = real(entry, evidence)
        if order == "cancel_after_store" and not answers:
            answers.append(other.cancel(USER, card_id(ctx)).status)
        return stored

    bench.outbox.enqueue = enqueue
    if op == "preview":
        bench.new_autopilot().preview(USER, ctx, result)
    else:
        assert bench.ap.send(USER, card_id(ctx)).status == "refused"
    assert answers == ["cancelled"]
    assert all(e["state"] == "cancelled" for e in bench.outbox.all())
    never_sent(bench)


OPS = st.lists(
    st.sampled_from(["down", "up", "replay", "send", "cancel", "edit", "advance", "dispatch"]), min_size=1, max_size=14
)


@needs_autopilot
@settings(max_examples=80, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(OPS, st.booleans())
def test_FR_CHN_11_no_send_after_a_confirmed_stop_while_the_outbox_flaps(ops, down_at_preview) -> None:
    bench = make_bench("L2")
    state = flaky(bench)
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    state["down"] = down_at_preview
    try:
        bench.ap.preview(USER, ctx, result)
    except Down:
        pass
    pending = autopilot_module().CancelPending
    stopped_at = None  # the clock when a Cancel or Edit of the L2 card was confirmed
    for i, op in enumerate(ops):
        if op in ("down", "up"):
            state["down"] = op == "down"
        elif op == "advance":
            bench.rig.clock.advance(25)
        elif op == "dispatch":
            bench.outbox.dispatch_due()
        else:
            try:
                if op == "replay":
                    bench.new_autopilot().preview(USER, ctx, result)
                elif op == "send":
                    bench.ap.send(USER, card_id(ctx))
                elif op == "cancel" and bench.ap.cancel(USER, card_id(ctx)).status == "cancelled":
                    stopped_at = stopped_at if stopped_at is not None else bench.rig.clock()
                elif op == "edit" and bench.ap.edit(USER, card_id(ctx), "x", instruction_id=f"ins-f{i}") is not None:
                    stopped_at = stopped_at if stopped_at is not None else bench.rig.clock()
            except (Down, pending):
                pass
    state["down"] = False
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    policy_sends = [(e, when) for e, when in bench.outbox.sent if bench.outbox.entries[e]["authz"]["by"] == "policy"]
    assert len(policy_sends) <= 1
    if stopped_at is not None:
        assert all(when.timestamp() < stopped_at for _, when in policy_sends), "sent after a confirmed stop"
