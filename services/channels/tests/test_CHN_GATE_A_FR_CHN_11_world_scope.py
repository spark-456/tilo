"""CHN-GATE-A security fix (PR #280 review): a stop is settled only in the world its card was decided in. The card
record carries its world; an Autopilot of another world (another tenant's sweeper, or a Cancel or Edit through a
wrongly wired instance) never answers "cancelled" for it, never writes `#cancelled`, leaves its queued stop for the
card's own world, and never creates the card's entry in its own world. PRD 11.6 "no send after cancel".

Real `tilo_connectors.Outbox` and `InMemoryOutboxStore` (FR-CHN-13's line: fake Gmail, fake clock), OB-01 evidence
skipped as in BQ-184. No network, no real mail.
"""

from __future__ import annotations

from typing import Any

import pytest
from _chn11_lib import RUN, WORLD, autopilot_module, fake_evidence_kwargs
from _chn13_lib import USER, Line, iso, make_line, outbox_skips_ob01_evidence
from _chn_gate_a_lib import MemoryStopQueue
from tilo_connectors import Outbox

OTHER = "w_another_tenant"
STOP_SIDE = ("revoke", "cancel", "get", "get_by_idempotency_key")


@pytest.fixture(autouse=True, scope="module")
def _ob01_evidence_is_not_this_ticket():
    with outbox_skips_ob01_evidence():
        yield


class DownOutbox:
    """The real outbox with `down` calls unavailable."""

    def __init__(self, real: Outbox, down: tuple[str, ...]) -> None:
        self._real, self._down = real, down

    def __getattr__(self, name: str) -> Any:
        if name in self._down:

            def unavailable(*args: Any) -> Any:
                raise ConnectionError(f"outbox unavailable ({name})")

            return unavailable
        return getattr(self._real, name)


def autopilot(line: Line, world: str, stops: MemoryStopQueue | None, outbox: Any = None) -> Any:
    bench = line.bench
    return autopilot_module().Autopilot(
        drafter=bench.rig.svc,
        reader=bench.rig.reader,
        contacts=bench.contacts,
        policy=bench.policy,
        outbox=outbox if outbox is not None else line.outbox,
        cards=bench.cards,
        clock=bench.rig.clock,
        emit=bench.events,
        world_id=world,
        run_id=RUN,
        stops=stops,
        **fake_evidence_kwargs(),
    )


def other_outboxes(line: Line) -> list[Any]:
    """Another world's view of the same store: unscoped, and scoped to that world."""
    return [line.outbox, Outbox(line.store, {}, lambda part: None, lambda: iso(line.clock()), world_id=OTHER)]


def card_of(line: Line, stops: MemoryStopQueue, *, enqueue_down: bool = False) -> Any:
    ctx, result = line.draft(line.thread())
    if not enqueue_down:
        card = autopilot(line, WORLD, stops).preview(USER, ctx, result)
        assert card.level == "L2" and line.store.get(card.outbox_id)["state"] == "scheduled", "test setup"
        return card
    with pytest.raises(ConnectionError):
        autopilot(line, WORLD, stops, DownOutbox(line.outbox, ("enqueue",))).preview(USER, ctx, result)
    assert line.entries() == [], "test setup: the preview stored nothing"
    return autopilot_module()._card_id(USER, ctx.instruction_id), ctx, result


def nothing_sent(line: Line) -> None:
    for _ in range(3):
        line.advance(600)
        line.dispatch()
    assert line.api.sent == [], "a mail was sent after its stop"
    assert all(e["state"] != "sent" for e in line.entries())


@pytest.mark.parametrize("which", ["unscoped", "scoped"])
def test_CHN_GATE_A_FR_CHN_11_another_worlds_sweep_never_settles_a_card(which: str) -> None:
    line, stops = make_line("L2"), MemoryStopQueue()
    card = card_of(line, stops)
    line.advance(10)
    with pytest.raises(autopilot_module().CancelPending):
        autopilot(line, WORLD, stops, DownOutbox(line.outbox, STOP_SIDE)).cancel(USER, card.card_id)
    outbox = other_outboxes(line)[which == "scoped"]
    for _ in range(2):
        assert autopilot(line, OTHER, stops, outbox).sweep() == {}, "another world's sweep touched the card"
    assert stops.pending() == [(USER, card.card_id)], "another world's sweep dropped the queued stop"
    assert autopilot(line, WORLD, stops).stop_state(USER, card.card_id) == "pending"
    assert line.store.get(card.outbox_id)["state"] == "scheduled"
    with pytest.raises(autopilot_module().CancelPending):  # a retry through the wrong world is still not confirmed
        autopilot(line, OTHER, stops, outbox).cancel(USER, card.card_id)
    line.advance(10)
    assert autopilot(line, WORLD, stops).sweep() == {(USER, card.card_id): "cancelled"}
    assert line.store.get(card.outbox_id)["state"] == "cancelled" and stops.pending() == []
    nothing_sent(line)


@pytest.mark.parametrize("sweeper", [True, False])
@pytest.mark.parametrize("op", ["cancel", "edit"])
def test_CHN_GATE_A_FR_CHN_11_a_wrong_world_cancel_or_edit_is_never_cancelled(op: str, sweeper: bool) -> None:
    line, stops = make_line("L2"), MemoryStopQueue()
    card = card_of(line, stops)
    line.advance(10)
    for outbox in other_outboxes(line):
        wrong = autopilot(line, OTHER, stops if sweeper else None, outbox)
        with pytest.raises(autopilot_module().CancelPending):
            if op == "cancel":
                wrong.cancel(USER, card.card_id)
            else:
                wrong.edit(USER, card.card_id, "add a thank you", instruction_id="ins-world-edit")
        assert line.store.get(card.outbox_id)["state"] == "scheduled"
        assert wrong.stop_state(USER, card.card_id) == "pending"
    right = autopilot(line, WORLD, stops if sweeper else None)
    if sweeper:
        assert right.sweep() == {(USER, card.card_id): "cancelled"}
    else:
        assert right.cancel(USER, card.card_id).status == "cancelled"
    assert line.store.get(card.outbox_id)["state"] == "cancelled"
    nothing_sent(line)


def test_CHN_GATE_A_FR_CHN_11_a_wrong_world_replay_or_send_never_creates_the_entry() -> None:
    line, stops = make_line("L2"), MemoryStopQueue()
    card_id, ctx, result = card_of(line, stops, enqueue_down=True)
    wrong = autopilot(line, OTHER, stops)
    with pytest.raises(PermissionError):
        wrong.preview(USER, ctx, result)
    with pytest.raises(PermissionError):
        wrong.send(USER, card_id)
    assert line.entries() == [], "an entry was created in another world"
    with pytest.raises(autopilot_module().CancelPending):  # never-stored card, wrong world: no revocation proves it
        wrong.cancel(USER, card_id)
    assert autopilot(line, OTHER, stops).sweep() == {}
    assert autopilot(line, WORLD, stops).sweep() == {(USER, card_id): "cancelled"}
    autopilot(line, WORLD, stops).preview(USER, ctx, result)  # the card's own world: the revoked key stays refused
    assert line.entries() == []
    nothing_sent(line)
