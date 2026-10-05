"""ST-3b / OB-01 (#204, #155, security round 1 on PR #209): after a writer commits a card's resolution and then raises,
the card resolves under the COMMITTED event. A later answer from another channel or user (same event id, other
content) is refused as `already_resolved`, the gate opens once with the committed event's authz, nothing is stuck on a
503, and there is one send. A write in flight is a retryable `busy`; tick treats a committed resolution as resolved and
one card's failure never blocks the others. Uses the content-checking StreamWriter from `_clint2_lib`.
"""

from __future__ import annotations

import threading
import time

import pytest
from _cards_lib import (
    OWNER_P,
    FakeClock,
    FakeEventWriter,
    answer_client,
    clone_card,
    load_valid_card,
    new_ulid,
    principal,
)
from _clint2_lib import wait_for
from tilo_api import cards
from tilo_api.cards import CardStore

W = "w_01"
START = "2026-09-29T09:30:00.000Z"
REFUSED = {"outcome": "rejected", "reason": "already_resolved"}
BUSY = {"outcome": "rejected", "reason": "busy"}  # a write is in flight and may still fail: retryable


def _count_sends(run_flow) -> tuple[int, int, int]:
    """(approval.resolved events, outbox entries, sends the connector made)."""
    return (
        len(run_flow.events("approval.resolved")),
        len(run_flow.outbox_store.all_entries()),
        len(run_flow.adapter.sent),
    )


def _commit_then_raise(run_flow, monkeypatch) -> None:
    """The content-checking StreamWriter commits the first approval.resolved and then raises."""
    real, raised = run_flow.writer.append, []

    def commit_then_raise(world_id: str, event: dict) -> dict:
        committed = real(world_id, event)
        if event["type"] == "approval.resolved" and not raised:
            raised.append(event["id"])
            raise OSError("the reply was lost after the commit")
        return committed

    monkeypatch.setattr(run_flow.writer, "append", commit_then_raise)


@pytest.mark.parametrize(
    ("first", "second"),
    [({"channel": "web"}, {"channel": "mobile_web"})],
    ids=["web_then_mobile_web"],
)
def test_ST_3b_OB_01_another_channel_after_a_commit_then_raise_resolves_under_the_committed_event(
    run_flow, monkeypatch, first, second
):
    _, card = run_flow.run_to_gate()
    _commit_then_raise(run_flow, monkeypatch)
    url = f"/worlds/{run_flow.world_id}/cards/{card['id']}/answer"
    post = run_flow.flow.client.post

    assert post(url, json={"option": "approve", **first}).status_code == 503  # committed, the caller saw a failure
    later = post(url, json={"option": "approve", **second})
    assert (later.status_code, later.json()) == (400, REFUSED)  # no lasting 503: the committed answer won
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")  # the gate opened
    run_flow.quiet_stream()

    for body in ({"option": "approve", **first}, {"option": "approve", **second}):  # and nothing re-opens it
        again = post(url, json=body)
        assert (again.status_code, again.json()) == (400, REFUSED)
    (entry,) = run_flow.outbox_store.all_entries()
    assert entry["authz"] == run_flow.events("approval.resolved")[0]["authz"]  # opened by the committed event
    assert _count_sends(run_flow) == (1, 1, 1)


class ConflictWriter:
    """Commits the first `fail_type` part and then raises; raises AlreadyCommitted for a resent id whose content
    differs (the writer contract in cards.EventWriter)."""

    def __init__(self, fail_type: str) -> None:
        self.committed: dict[str, dict] = {}
        self.fail_type, self.raised = fail_type, False

    def write(self, part: dict) -> None:
        known = self.committed.get(part["event_id"])
        if known is not None and known != part:
            raise cards.AlreadyCommitted(part["event_id"])
        self.committed[part["event_id"]] = part
        if part["type"] == self.fail_type and not self.raised:
            self.raised = True
            raise OSError("the reply was lost after the commit")


def test_ST_3b_OB_01_the_owner_after_an_approvers_commit_then_raise_is_refused_not_stuck():
    card, clock = load_valid_card("gate_send_reply"), FakeClock(START)
    writer = ConflictWriter("approval.resolved")
    store = CardStore(clock=clock, writer=writer, world_owners={W: "u_owner"})
    store.submit(card, outbox_id=new_ulid("ob"), assignee="u_approver")
    approver = principal("approver", "u_approver")

    def approve(who):
        clock.advance(5)  # the part's `at` differs on every rebuild
        return store.answer(W, card["id"], option="approve", channel="web", principal=who)

    with pytest.raises(OSError):
        approve(approver)
    refused = approve(OWNER_P)
    assert (refused.outcome, refused.reason) == ("rejected", "already_resolved")
    assert approve(approver).reason == "already_resolved"
    assert len(writer.committed) == 1 and store.list_for_world(W, principal=OWNER_P) == []


def test_ST_3b_OB_01_a_retry_after_a_commit_then_raise_survives_a_level_change_in_the_run(run_flow, monkeypatch):
    """The resent event is the first one as built, so a level that moved between the attempt and the retry is not a
    conflict."""
    _, card = run_flow.run_to_gate()
    _commit_then_raise(run_flow, monkeypatch)
    assert run_flow.answer(card["id"], "approve").status_code == 503
    run = run_flow.store.runs[run_flow.world_id]
    run.levels = dict.fromkeys(run.levels, "L_moved")

    assert run_flow.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    run_flow.quiet_stream()
    assert _count_sends(run_flow) == (1, 1, 1)


class SlowWriter(FakeEventWriter):
    def write(self, part: dict) -> None:
        time.sleep(0.3)
        super().write(part)


def test_ST_3b_OB_01_an_answer_while_a_write_is_in_flight_is_busy_and_retryable_not_already_resolved():
    writer, card = SlowWriter(), load_valid_card("needs_you_blocked")
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={W: "u_owner"})
    store.submit(card)
    client = answer_client(store, OWNER_P)
    url = f"/worlds/{W}/cards/{card['id']}/answer"
    first = threading.Thread(target=lambda: client.post(url, json={"option": "per_kwh"}))
    first.start()
    time.sleep(0.1)  # the first write is in flight

    busy = client.post(url, json={"option": "per_pack"})
    first.join()
    refused = client.post(url, json={"option": "per_pack"})

    assert (busy.status_code, busy.json()) == (409, BUSY)
    assert (refused.status_code, refused.json()) == (400, REFUSED)
    assert [p["type"] for p in writer.parts] == ["question.answered"]


class FailsFor(FakeEventWriter):
    """Raises for the listed card ids, records the rest."""

    def __init__(self, *bad: str) -> None:
        super().__init__()
        self.bad = set(bad)

    def write(self, part: dict) -> None:
        if part["card_id"] in self.bad:
            raise RuntimeError("the writer is down for this card")
        super().write(part)


def _questions(writer, *seeds: str) -> tuple[CardStore, FakeClock, list[dict]]:
    """Open question cards in separate buildings (so none merge), `advance` seconds past their deadline."""
    clock, base = FakeClock(START), load_valid_card("needs_you_blocked")
    store = CardStore(clock=clock, writer=writer, world_owners={W: "u_owner"})
    made = [clone_card(base, id_=new_ulid(s), building=f"B{n + 3}") for n, s in enumerate(seeds)]
    for card in made:
        assert store.submit(card).outcome == "accepted"
    return store, clock, made


def test_ST_3b_OB_01_tick_treats_an_already_committed_resolution_as_resolved():
    writer = ConflictWriter("question.answered")
    store, clock, (card,) = _questions(writer, "q1")
    with pytest.raises(OSError):  # a person's answer commits, then the writer raises
        store.answer(W, card["id"], option="per_kwh", channel="web", principal=OWNER_P)
    clock.advance(card["timeout"] + 1)

    assert [r.card_id for r in store.tick()] == [card["id"]]  # the default conflicts: already resolved, no raise
    assert store.list_for_world(W, principal=OWNER_P) == [] and store.tick() == []
    assert len(writer.committed) == 1


def test_ST_3b_OB_01_one_cards_failure_in_tick_never_blocks_the_others():
    writer = FailsFor(new_ulid("bad"))
    store, clock, (bad, good1, good2) = _questions(writer, "bad", "ok1", "ok2")
    clock.advance(bad["timeout"] + 1)

    with pytest.raises(RuntimeError):
        store.tick()

    assert sorted(p["card_id"] for p in writer.of_type("question.answered")) == sorted([good1["id"], good2["id"]])
    assert [c["id"] for c in store.list_for_world(W, principal=OWNER_P)] == [
        bad["id"]
    ]  # still open: the next tick retries
