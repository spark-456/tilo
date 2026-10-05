"""FR-HIL-10 (PRD 10.2 "Needs you: that branch waits", 10.3 "same-type cards from one district within 60 s merge",
10.6 "answering resumes the agent in <= 2 s") and FR-HIL-02, issue #338, through the real `Run` and `CardStore`.

DECISION (issue #338, item 1): a question card a unit waits on is NEVER merged with another card. Each unit's question
and options mean something different, and one click must not answer a question the person never saw. So two units of
ONE district that ask within 60 s give TWO listed cards; each answer resumes only its own unit; each card gets exactly
one `question.answered`; and a plain card (a gate, or any card handed to `CardStore.submit` as before) still merges.
`CardStore.submit(card, ..., merge=False)` is the knob (name pinned: `merge: bool = True`).

Also pinned here: `tilo_api.cards.AlreadyCommitted` is the harness's class (`tilo_harness.question_wait`), and a
failure of `CardStore.tick()` after the harness already committed a deadline default never reaches the waiter.
The harness half of the claim races is in `services/harness/tests/test_FR_HIL_10_claim_races.py`.

Everything is scripted: no model, no network, no timer longer than the run itself (EFF-01).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
from _agt05_lib import (
    ASK,
    CLEAR,
    RESUME_BUDGET_S,
    build_ask_flow,
    needs_you_cards,
    start_and_approve,
    task,
    tasks_provider,
)
from _cards_lib import OWNER_P, FakeClock, FakeEventWriter, add_seconds, clone_card, load_valid_card
from _clint2_lib import wait_for
from tilo_api.cards import CardStore

ASK_2 = task("ASK-01")  # "Update the pricing sheet ...": its own question and options, a different unit
OWNER = "u_owner"
START = "2026-09-29T09:30:00.000Z"
TERMINAL = ("world.completed", "world.failed")


@pytest.fixture()
def two_asking(repo_root):
    """A builder (not a ready run) of a run whose U1 and U2 are in ONE district (D1, one Workshop) and both ask a
    question; U3 (district D2) depends on U2. Returns (RunFlow, [the needs_you cards listed])."""
    flows = []

    def build():
        provider = tasks_provider(ASK, ASK_2, CLEAR[2])
        rf = build_ask_flow(repo_root, provider, independent=True)
        flows.append(rf)
        scripted = rf.compile_plan

        def compile_plan(**kwargs):
            plan = scripted(**kwargs)
            assert plan["units"][0]["district"] == plan["units"][1]["district"], "the two units share a district"
            plan["units"][1]["title"] = ASK_2["title"]  # U2 asks too (a different question)
            return plan

        rf.compile_plan = compile_plan
        start_and_approve(rf)
        wait_for(lambda: len(rf.events("question.routed")) == 2, what="both units' question.routed")
        rf.quiet_stream()
        return rf, needs_you_cards(rf)

    yield build
    for rf in flows:
        rf.close()


# --- A. merged same-district question cards -----------------------------------------------------------------------


def test_FR_HIL_10_two_units_of_one_district_asking_within_60_s_list_two_cards(two_asking):
    rf, cards = two_asking()

    routed = rf.events("question.routed")
    assert len(routed) == 2 and routed[0]["district"] == routed[1]["district"], "two questions from one district"
    assert len({e["data"]["card_id"] for e in routed}) == 2
    assert len(cards) == 2, f"each unit's question is its own card, never merged: {[c['id'] for c in cards]}"
    assert {c["id"] for c in cards} == {e["data"]["card_id"] for e in routed}, "every routed card is listed"
    assert cards[0]["what_happened"] != cards[1]["what_happened"], "they really are two different questions"


def test_FR_HIL_10_each_same_district_card_resumes_only_its_own_unit_and_writes_one_answer(two_asking):
    rf, cards = two_asking()
    assert len(cards) == 2, "the two same-district questions must be two cards"
    first, second = cards

    t0 = time.monotonic()
    response = rf.answer(first["id"], first["options"][1]["id"])
    assert response.status_code == 200 and response.json() == {"outcome": "answered"}, response.text
    wait_for(lambda: {"U1", "U2"} & set(rf.runner.started_at), timeout=RESUME_BUDGET_S + 1, what="a unit to resume")
    assert time.monotonic() - t0 <= RESUME_BUDGET_S, "FR-HIL-10: answering resumes the unit in <= 2 s"
    (first_unit,) = {"U1", "U2"} & set(rf.runner.started_at)
    other = ({"U1", "U2"} - {first_unit}).pop()
    rf.quiet_stream()

    assert other not in rf.runner.started_at, "answering card 1 must not resume the unit that asked card 2"
    assert [c["id"] for c in needs_you_cards(rf)] == [second["id"]], "card 2 stays open and listed"
    assert len(rf.events("question.answered")) == 1
    assert not [e for e in rf.stream() if e["type"] in TERMINAL], "the run still waits for the second answer"
    answer = rf.runner.answers[first_unit]
    assert (answer.card_id, answer.option, answer.answered_by) == (first["id"], first["options"][1]["id"], "person")

    t1 = time.monotonic()
    response = rf.answer(second["id"], second["options"][0]["id"])
    assert response.status_code == 200 and response.json() == {"outcome": "answered"}, response.text
    wait_for(lambda: other in rf.runner.started_at, timeout=RESUME_BUDGET_S + 1, what="the other unit to resume")
    assert rf.runner.started_at[other] - t1 <= RESUME_BUDGET_S
    answer = rf.runner.answers[other]
    assert (answer.card_id, answer.option, answer.answered_by) == (second["id"], second["options"][0]["id"], "person")

    wait_for(lambda: rf.events("world.completed"), what="world.completed after both answers")
    events = rf.quiet_stream()
    answered = [e for e in events if e["type"] == "question.answered"]
    assert len(answered) == 2 and len({e["id"] for e in answered}) == 2, "one question.answered per card, no more"
    assert [e["data"]["answered_by"] for e in answered] == ["person", "person"]
    assert [e["type"] for e in events].count("world.completed") == 1
    assert "world.failed" not in [e["type"] for e in events]
    assert rf.runner.ran.count("U1") == 1 and rf.runner.ran.count("U2") == 1
    assert needs_you_cards(rf) == []
    for card in cards:  # a closed card is answered once: a second click changes nothing
        assert rf.answer(card["id"], card["options"][0]["id"]).status_code in (400, 404, 409)
    assert len(rf.quiet_stream(0.3)) == len(events), "nothing more is written, no second question.answered"


def test_FR_HIL_10_answering_the_second_card_first_resumes_the_second_unit_only(two_asking):
    rf, cards = two_asking()
    assert len(cards) == 2, "the two same-district questions must be two cards"

    assert rf.answer(cards[1]["id"], cards[1]["options"][0]["id"]).status_code == 200
    wait_for(lambda: {"U1", "U2"} & set(rf.runner.started_at), what="a unit to resume")
    rf.quiet_stream()
    (resumed,) = {"U1", "U2"} & set(rf.runner.started_at)
    waiting = ({"U1", "U2"} - {resumed}).pop()

    assert rf.runner.answers[resumed].card_id == cards[1]["id"]
    assert waiting not in rf.runner.started_at and [c["id"] for c in needs_you_cards(rf)] == [cards[0]["id"]]
    assert rf.answer(cards[0]["id"], cards[0]["options"][0]["id"]).status_code == 200
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    assert rf.runner.answers[waiting].card_id == cards[0]["id"]
    rf.quiet_stream()
    assert len(rf.events("question.answered")) == 2


def _plain(index: int, created_at: str = START) -> dict:
    base = load_valid_card("needs_you_compare_basis")
    return clone_card(base, id_=f"01J8Z3K4M5N6P7Q8R9S0T1V9{index:02d}", created_at=created_at)


def _store(card: dict) -> tuple[CardStore, FakeEventWriter]:
    writer = FakeEventWriter()
    return CardStore(clock=FakeClock(START), writer=writer, world_owners={card["world_id"]: OWNER}), writer


def test_FR_HIL_02_three_plain_cards_from_one_district_still_merge_by_default():
    cards = [_plain(1), _plain(2, add_seconds(START, 10)), _plain(3, add_seconds(START, 55))]
    store, _writer = _store(cards[0])

    results = [store.submit(card) for card in cards]

    assert [r.outcome for r in results] == ["accepted", "merged", "merged"]
    assert [c["id"] for c in store.list_for_world(cards[0]["world_id"], principal=OWNER_P)] == [cards[0]["id"]]


def test_FR_HIL_10_a_card_submitted_with_merge_false_is_its_own_group():
    first, solo, later = _plain(11), _plain(12, add_seconds(START, 5)), _plain(13, add_seconds(START, 10))
    store, writer = _store(first)
    world = first["world_id"]

    r1 = store.submit(first)
    r2 = store.submit(solo, merge=False)
    r3 = store.submit(later)

    assert r1.outcome == "accepted"
    assert (r2.outcome, r2.card_id) == ("accepted", solo["id"]), "merge=False does not merge into an existing group"
    assert r3.card_id != solo["id"], "a later mergeable card does not merge into a merge=False card"
    listed = [c["id"] for c in store.list_for_world(world, principal=OWNER_P)]
    assert {first["id"], solo["id"]} <= set(listed), "the solo card is listed beside the group"

    answered = store.answer(world, solo["id"], option=solo["options"][0]["id"], channel="web", principal=OWNER_P)
    assert answered.outcome == "answered"
    assert [p["card_id"] for p in writer.of_type("question.answered")] == [solo["id"]]
    still = [c["id"] for c in store.list_for_world(world, principal=OWNER_P)]
    assert first["id"] in still and solo["id"] not in still, "answering the solo card closes nothing else"


def test_FR_HIL_10_two_merge_false_cards_in_the_window_stay_two_cards_and_two_answers():
    one, two = _plain(21), _plain(22, add_seconds(START, 1))
    store, writer = _store(one)

    assert store.submit(one, merge=False).outcome == "accepted"
    assert store.submit(two, merge=False).outcome == "accepted"
    assert {c["id"] for c in store.list_for_world(one["world_id"], principal=OWNER_P)} == {one["id"], two["id"]}

    for card in (one, two):
        result = store.answer(card["world_id"], card["id"], option=card["options"][0]["id"], channel="web",
                              principal=OWNER_P)  # fmt: skip
        assert result.outcome == "answered"
    assert sorted(p["card_id"] for p in writer.of_type("question.answered")) == sorted([one["id"], two["id"]])
    assert store.list_for_world(one["world_id"], principal=OWNER_P) == []


# --- B. the claim-race contract, API half ------------------------------------------------------------------------


def test_FR_HIL_10_cards_re_exports_the_harness_already_committed():
    from tilo_api import cards  # noqa: PLC0415
    from tilo_harness import question_wait  # noqa: PLC0415

    assert issubclass(question_wait.AlreadyCommitted, Exception)
    assert cards.AlreadyCommitted is question_wait.AlreadyCommitted, (
        "one class: the writer raises it, the store reads it"
    )


def test_FR_HIL_10_a_card_tick_failure_after_the_harness_default_does_not_fail_the_waiter(repo_root, monkeypatch):
    """Run.emit calls `cards.tick()` after the harness committed a deadline default (BQ-208). That tick raising once
    must not become an error for the waiting unit: it resumes with the safe default, `answered_by` default."""
    from tilo_harness import question_wait  # noqa: PLC0415

    def late_now(self):  # the card's deadline (created_at + 3600 s) has passed the moment the unit waits
        return datetime.now(UTC) + timedelta(seconds=3601)

    monkeypatch.setattr(question_wait.SystemClock, "now", late_now)
    ticks: list[int] = []
    original = CardStore.tick

    def tick(self):
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError("the card store could not tick (scripted)")
        return original(self)

    monkeypatch.setattr(CardStore, "tick", tick)
    rf = build_ask_flow(repo_root, tasks_provider(ASK, *CLEAR[1:]), independent=True)
    try:
        start_and_approve(rf)
        wait_for(lambda: rf.events("question.answered"), what="the harness default")
        wait_for(lambda: "U1" in rf.runner.started_at or rf.events("world.failed"), what="U1 to resume")

        assert ticks, "the default went through Run.emit and its tick"
        assert "U1" in rf.runner.started_at, "the waiter resumed; a tick failure is not its failure"
        answer = rf.runner.answers["U1"]
        assert (answer.answered_by, answer.option) == ("default", "o1"), (
            "ASK-06's suggested (safe default) option is o1"
        )
        wait_for(lambda: rf.events("world.completed"), what="world.completed")
        events = rf.quiet_stream()
        (answered,) = [e for e in events if e["type"] == "question.answered"]
        assert answered["data"]["answered_by"] == "default" and answered["severity"] == "nudge"
        assert "world.failed" not in [e["type"] for e in events]
    finally:
        rf.close()
