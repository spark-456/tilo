"""ST-3b / OB-01 (#204, #155): the cards API is first-answer-wins and idempotent per card. The web gate sheet lets a
person answer again after 20 s with no closing event, so a second answer to a card (the same option or another, in
sequence or at once, from web or WhatsApp) must write nothing and send nothing, and must get the stable
`already_resolved` refusal, never a 500. A writer that commits an event and then raises gives a 503 and then a 200 on
retry with one approval.resolved, because each card resolution has one stable event id (FR-HIL-07).
"""

from __future__ import annotations

import threading
import time

import pytest
from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, answer_client, load_valid_card, new_ulid
from _clint2_lib import wait_for
from tilo_api import cards
from tilo_api.cards import CardStore

W = "w_01"
START = "2026-09-29T09:30:00.000Z"
REFUSED = {"outcome": "rejected", "reason": "already_resolved"}
BUSY = {"outcome": "rejected", "reason": "busy"}  # a write is in flight and may still fail: retryable

# fixture, first option, another option, the channels the two answers come from, the event the first one writes
CASES = {
    "gate": ("gate_send_reply", "approve", "hold", ("whatsapp", "web"), "approval.resolved"),
    "consent": ("consent_drive_folder", "connect", "hold", ("web", "mobile_web"), "connection.consented"),
    "question": ("needs_you_blocked", "per_kwh", "per_pack", ("whatsapp", "web"), "question.answered"),
}


class SlowWriter(FakeEventWriter):
    """Records a part only after a pause, so a second caller arrives while the first is mid-write."""

    def write(self, part: dict) -> None:
        time.sleep(0.2)
        super().write(part)


def _store(kind: str, writer: FakeEventWriter | None = None) -> tuple[CardStore, dict, FakeEventWriter]:
    fixture = CASES[kind][0]
    card, writer = load_valid_card(fixture), writer or FakeEventWriter()
    store = CardStore(clock=FakeClock(START), writer=writer, world_owners={W: "u_owner"})
    store.submit(card, outbox_id=new_ulid("ob") if card["kind"] == "gate" else None)
    return store, card, writer


def _answer(store: CardStore, card: dict, option: str, channel: str = "web"):
    return store.answer(W, card["id"], option=option, channel=channel, principal=OWNER_P, pin_verified=True)


@pytest.mark.parametrize("kind", CASES)
@pytest.mark.parametrize("second", ["same", "other"])
def test_ST_3b_OB_01_a_second_answer_in_sequence_writes_nothing(kind, second):
    _, first, other, _channels, written = CASES[kind]
    store, card, writer = _store(kind)
    assert _answer(store, card, first).outcome == "answered"

    again = _answer(store, card, first if second == "same" else other)

    assert (again.outcome, again.reason, again.emitted) == ("rejected", "already_resolved", ())
    assert [p["type"] for p in writer.parts] == [written]


@pytest.mark.parametrize("kind", CASES)
def test_ST_3b_OB_01_the_second_answer_is_a_stable_refusal_not_a_500_and_a_resend_changes_nothing(kind):
    _, first, other, _channels, written = CASES[kind]
    store, card, writer = _store(kind)
    client = answer_client(store, OWNER_P)
    url = f"/worlds/{W}/cards/{card['id']}/answer"
    assert client.post(url, json={"option": first}).status_code == 200

    replies = [client.post(url, json={"option": o}) for o in (first, other, first)]

    assert [(r.status_code, r.json()) for r in replies] == [(400, REFUSED)] * 3
    assert [p["type"] for p in writer.parts] == [written]


@pytest.mark.parametrize("kind", CASES)
def test_ST_3b_OB_01_answers_at_once_from_two_channels_write_one_resolution(kind):
    _, first, other, (a, b), written = CASES[kind]
    store, card, writer = _store(kind, SlowWriter())
    calls = [(first, a), (first, b), (other if kind != "gate" else first, a), (first, b)] * 2
    results: list = [None] * len(calls)

    def run(i: int, option: str, channel: str) -> None:
        results[i] = _answer(store, card, option, channel)

    threads = [threading.Thread(target=run, args=(i, *call)) for i, call in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert [r.outcome for r in results].count("answered") == 1
    assert all(r.reason in ("busy", "already_resolved") for r in results if r.outcome == "rejected")
    assert [p["type"] for p in writer.parts] == [written]


@pytest.mark.parametrize("kind", CASES)
def test_ST_3b_OB_01_an_answer_from_the_other_channel_after_the_first_is_refused(kind):
    _, first, _other, (a, b), written = CASES[kind]
    for one, two in ((a, b), (b, a)):
        store, card, writer = _store(kind)
        assert _answer(store, card, first, one).outcome == "answered"
        assert _answer(store, card, first, two).reason == "already_resolved"
        assert [p["type"] for p in writer.parts] == [written]


def _count_sends(run_flow) -> tuple[int, int, int]:
    """(approval.resolved events, outbox entries, sends the connector made)."""
    return (
        len(run_flow.events("approval.resolved")),
        len(run_flow.outbox_store.all_entries()),
        len(run_flow.adapter.sent),
    )


def test_ST_3b_OB_01_the_run_sends_once_when_the_gate_is_answered_in_sequence_by_web_then_whatsapp(run_flow):
    run_flow.flow.app.dependency_overrides[cards.get_channels_caller] = lambda: True  # tilo-channels is the caller
    _, card = run_flow.run_to_gate()
    url = f"/worlds/{run_flow.world_id}/cards/{card['id']}/answer"
    assert run_flow.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    later = [
        run_flow.flow.client.post(url, json={"option": "approve", "channel": "web"}),
        run_flow.flow.client.post(url, json={"option": "approve", "channel": "whatsapp", "pin_verified": True}),
        run_flow.flow.client.post(url, json={"option": "hold", "channel": "whatsapp"}),
    ]

    assert [(r.status_code, r.json()) for r in later] == [(400, REFUSED)] * 3
    assert _count_sends(run_flow) == (1, 1, 1)


def test_ST_3b_OB_01_the_run_sends_once_when_the_gate_is_answered_at_once_from_web_and_whatsapp(run_flow):
    run_flow.flow.app.dependency_overrides[cards.get_channels_caller] = lambda: True
    _, card = run_flow.run_to_gate()
    url = f"/worlds/{run_flow.world_id}/cards/{card['id']}/answer"
    bodies = [
        {"option": "approve", "channel": "web"},
        {"option": "approve", "channel": "whatsapp", "pin_verified": True},
    ]
    replies: list = []

    def post(body: dict) -> None:
        replies.append(run_flow.flow.client.post(url, json=body))

    threads = [threading.Thread(target=post, args=(bodies[i % 2],)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    run_flow.quiet_stream()

    assert sorted(r.status_code for r in replies).count(200) == 1  # the rest: 409 busy (in flight) or 400 refused
    assert all(r.json() == (REFUSED if r.status_code == 400 else BUSY) for r in replies if r.status_code != 200)
    assert len(replies) == 8 and {r.status_code for r in replies} <= {200, 400, 409}
    assert _count_sends(run_flow) == (1, 1, 1)


def test_ST_3b_OB_01_a_writer_that_commits_then_raises_gives_a_503_then_a_200_with_one_resolution_and_one_send(
    run_flow, monkeypatch
):
    """#155: the event is committed and the writer still raises. The retry reuses the resolution's one event id, so
    nothing new is written (2 approval.resolved and 1 send before this fix, 1 and 1 now)."""
    _, card = run_flow.run_to_gate()
    real, raised = run_flow.writer.append, []

    def commit_then_raise(world_id: str, event: dict) -> dict:
        committed = real(world_id, event)
        if event["type"] == "approval.resolved" and not raised:
            raised.append(event["id"])
            raise OSError("the reply was lost after the commit")
        return committed

    monkeypatch.setattr(run_flow.writer, "append", commit_then_raise)
    down = run_flow.answer(card["id"], "approve")
    assert (down.status_code, down.json()) == (503, {"outcome": "error", "reason": "event_write_failed"})
    assert len(run_flow.events("approval.resolved")) == 1  # committed, though the caller was told it failed

    assert run_flow.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    run_flow.quiet_stream()

    assert _count_sends(run_flow) == (1, 1, 1)
    assert run_flow.events("approval.resolved")[0]["id"] == raised[0]


def test_ST_3b_OB_01_each_card_resolution_has_one_stable_event_id_that_differs_between_cards():
    ids = []
    for kind in CASES:
        _, first, _other, _channels, _written = CASES[kind]
        ids.append([_resolution_id(kind, first) for _ in range(2)])
    assert all(a == b for a, b in ids)  # the same card and option always give the same id
    assert len({a for a, _ in ids}) == len(CASES)


def _resolution_id(kind: str, option: str) -> str:
    store, card, writer = _store(kind)
    _answer(store, card, option)
    return writer.parts[0]["event_id"]
