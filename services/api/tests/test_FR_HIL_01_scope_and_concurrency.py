"""FR-HIL-01 / FR-HIL-02 security review of PR #121: every written part carries its world and scope
(SEC-07, FR-HIL-09), and exactly one resolution is written per card even when answers and the
timeout race (one approval.resolved per gate, OB-01).
"""

from __future__ import annotations

import threading
import time

import pytest
from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, clone_card, load_valid_card, new_ulid, principal
from tilo_api.cards import CardStore

START = "2026-09-29T09:30:00.000Z"
W = "w_01"
APPROVER = "u_approver"


class SlowWriter(FakeEventWriter):
    """Records a part only after a pause, so a second caller can arrive mid-write."""

    def __init__(self, pause: float = 0.3, fail: bool = False) -> None:
        super().__init__()
        self.pause, self.fail, self.started = pause, fail, threading.Event()

    def write(self, part: dict) -> None:
        self.started.set()
        time.sleep(self.pause)
        if self.fail:
            raise RuntimeError("writer down")
        super().write(part)


def _store(writer=None, worlds=(W,)) -> tuple[CardStore, FakeClock, FakeEventWriter]:
    clock, writer = FakeClock(START), writer or FakeEventWriter()
    return CardStore(clock=clock, writer=writer, world_owners=dict.fromkeys(worlds, "u_owner")), clock, writer


def _in_threads(*calls):
    out: list = [None] * len(calls)

    def run(i, call):
        out[i] = call()

    threads = [threading.Thread(target=run, args=(i, c)) for i, c in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


# -- scope on every part -------------------------------------------------------------------------


def test_FR_HIL_01_SEC_07_a_d2_cards_answer_and_timeout_parts_carry_district_d2_and_vis_d2():
    store, clock, writer = _store()
    question, gate = load_valid_card("needs_you_blocked"), load_valid_card("gate_send_reply")
    store.submit(question, district="D2")
    store.submit(gate, outbox_id=new_ulid("ob"), district="D2")
    clock.advance(question["timeout"])
    store.tick()  # default question.answered for the question, alert.raised for the held gate
    store.answer(W, gate["id"], option="approve", channel="web", principal=OWNER_P)

    assert {p["type"] for p in writer.parts} == {"question.answered", "alert.raised", "approval.resolved"}
    for part in writer.parts:
        assert (part["world_id"], part["district"], part["vis"], part["owner_only"]) == (W, "D2", ["D2"], False)
        assert part["card_id"] in (question["id"], gate["id"])


def test_FR_HIL_01_SEC_07_an_owner_only_card_never_carries_vis_all():
    """event vis cannot express owner-only, so the part says so explicitly instead of vis "all"."""
    store, _clock, writer = _store()
    card = load_valid_card("needs_you_blocked")
    store.submit(card)
    store.answer(W, card["id"], option="per_kwh", channel="web", principal=OWNER_P)

    [part] = writer.parts
    assert (part["district"], part["vis"], part["owner_only"]) == (None, None, True)


def test_FR_HIL_01_SEC_07_parts_from_two_worlds_are_distinguishable():
    store, _clock, writer = _store(worlds=("w_01", "w_02"))
    one = load_valid_card("needs_you_blocked")
    two = clone_card(one)
    two["world_id"] = "w_02"
    for card, who in ((one, OWNER_P), (two, principal(world_id="w_02"))):
        store.submit(card, district="D2")
        store.answer(card["world_id"], card["id"], option="per_kwh", channel="web", principal=who)

    assert [p["world_id"] for p in writer.parts] == ["w_01", "w_02"]
    assert writer.parts[0] != writer.parts[1]


# -- exactly one resolution per card -----------------------------------------------------------


def test_FR_HIL_01_two_approvers_racing_one_gate_write_one_approval_resolved():
    writer = SlowWriter()
    store, _clock, _ = _store(writer)
    card = load_valid_card("gate_send_reply")
    store.submit(card, outbox_id=new_ulid("ob"), assignee=APPROVER)

    def approve(who):
        return lambda: store.answer(W, card["id"], option="approve", channel="web", principal=who).reason

    reasons = _in_threads(approve(OWNER_P), approve(principal("approver", APPROVER)))

    assert sorted(r or "ok" for r in reasons) == ["already_resolved", "ok"]
    assert len(writer.of_type("approval.resolved")) == 1


def test_FR_HIL_02_a_persons_answer_racing_tick_writes_one_question_answered():
    writer = SlowWriter()
    store, clock, _ = _store(writer)
    card = load_valid_card("needs_you_blocked")
    store.submit(card)
    clock.advance(card["timeout"])  # due, but a person is answering this very moment

    def answer():
        return store.answer(W, card["id"], option="per_kwh", channel="web", principal=OWNER_P).outcome

    def tick_once_writing():
        writer.started.wait(2)
        return store.tick()

    outcomes = _in_threads(answer, tick_once_writing)

    assert outcomes == ["answered", []]
    assert [p["data"]["answered_by"] for p in writer.of_type("question.answered")] == ["person"]


def test_FR_HIL_01_a_failed_write_leaves_the_card_open_to_answer_again():
    writer = SlowWriter(pause=0, fail=True)
    store, _clock, _ = _store(writer)
    card = load_valid_card("gate_send_reply")
    store.submit(card, outbox_id=new_ulid("ob"))

    with pytest.raises(RuntimeError):
        store.answer(W, card["id"], option="approve", channel="web", principal=OWNER_P)
    writer.fail = False

    assert store.answer(W, card["id"], option="approve", channel="web", principal=OWNER_P).outcome == "answered"
    assert len(writer.of_type("approval.resolved")) == 1


def test_FR_HIL_02_a_failed_timeout_write_is_retried_by_the_next_tick():
    writer = SlowWriter(pause=0, fail=True)
    store, clock, _ = _store(writer)
    card = load_valid_card("needs_you_blocked")
    store.submit(card)
    clock.advance(card["timeout"])

    with pytest.raises(RuntimeError):
        store.tick()
    writer.fail = False

    assert [r.card_id for r in store.tick()] == [card["id"]]


# -- cheap follow-ups --------------------------------------------------------------------------------


def test_FR_HIL_01_a_team_leads_question_answer_is_written_as_team_lead():
    store, _clock, writer = _store()
    card = load_valid_card("needs_you_blocked")
    store.submit(card, district="D1")

    lead = principal("team_lead", "u_lead", districts=("D1",))
    store.answer(W, card["id"], option="per_kwh", channel="web", principal=lead)

    assert writer.parts[0]["data"] == {"answered_by": "team_lead"}


def test_FR_HIL_01_an_unknown_role_fails_closed_like_a_viewer():
    store, _clock, writer = _store()
    card = load_valid_card("needs_you_blocked")
    store.submit(card)
    stranger = principal("contractor", "u_owner")  # even under the owner's own id

    with pytest.raises(PermissionError):
        store.list_for_world(W, principal=stranger)
    assert store.answer(W, card["id"], option="per_kwh", channel="web", principal=stranger).reason == "forbidden"
    assert writer.parts == []
