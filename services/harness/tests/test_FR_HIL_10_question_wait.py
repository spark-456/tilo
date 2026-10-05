"""FR-HIL-10 (PRD 10.6, harness half): "answering resumes the agent in <= 2 s", and PRD 10.3 "Every card
has a timeout and a safe default; the Director applies the default and posts a Nudge saying so".

Given an agent waiting on a routed question, When `question.answered` arrives (a person's or a Team Lead's,
as the API's CardStore hands it over) Then the agent resumes with that option within 2.0 s of real time with a
0.5 s event writer on the path and a fake clock that never moves (so no timer or poll can hide a delay); When
nobody answers by the card's deadline Then the harness posts the default as a Nudge and resumes with the card's
safe default. Interface and defaults: `hil_wait_support.py`, BQ-207..BQ-209 in docs/open-questions.md.
"""

from __future__ import annotations

import asyncio
import time

from conftest import make_memory_writer
from hil_wait_support import (
    CARD_CREATED,
    DIRECTOR,
    DISTRICT,
    LEAD,
    RESUME_BUDGET_S,
    SLOW_WRITER_S,
    WORLD,
    FakeAsyncClock,
    SlowWriter,
    answered_part,
    events_of,
    layout,
    make_card,
    settle,
    until,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_harness.question_wait import Answer, QuestionWait


def _world():
    writer, store = make_memory_writer(layout(), world_id=WORLD)
    slow = SlowWriter(writer)
    clock = FakeAsyncClock()
    return QuestionWait(slow, clock=clock), slow, clock, store


async def _park(wait, clock, card):
    task = asyncio.ensure_future(wait.wait_for(card, lead=LEAD, director=DIRECTOR, district=DISTRICT))
    await until(lambda: clock.pending_sleepers() >= 1 or task.done())
    return task


def _answered(store):
    return events_of(store, "question.answered")


def test_FR_HIL_10_answer_resumes_the_waiting_agent_within_2_s() -> None:
    async def go():
        wait, slow, clock, store = _world()
        card = make_card()
        task = await _park(wait, clock, card)
        part = answered_part(card, by="person", option="per_pack")
        slow.delay_s = SLOW_WRITER_S
        started = time.perf_counter()
        await asyncio.to_thread(wait.write, part)  # the API calls from its own thread
        await until(task.done)
        elapsed = time.perf_counter() - started
        return task.result(), elapsed, clock, store, part

    answer, elapsed, clock, store, part = asyncio.run(go())

    assert answer == Answer(card_id=part["card_id"], option="per_pack", answered_by="person")
    assert elapsed <= RESUME_BUDGET_S, f"FR-HIL-10: answering must resume the agent in <= 2 s, took {elapsed:.2f} s"
    assert elapsed >= SLOW_WRITER_S, "the 0.5 s writer really was on the path (the event is committed before resume)"
    assert clock.now() == CARD_CREATED, "the fake clock was never advanced: no timer produced this"
    (event,) = _answered(store)
    assert event["id"] == part["event_id"], "committed under the part's own id (FR-HIL-07 resend safety)"
    assert {k: v for k, v in event["data"].items() if k != "decision_id"} == {"answered_by": "person"}
    assert (event["district"], event["vis"], event["severity"], event["target"]) == (DISTRICT, [DISTRICT], "info", LEAD)
    assert [e["seq"] for e in store.read_events("org_demo", WORLD)] == [event["seq"]]


def test_FR_HIL_10_team_lead_answer_resumes_with_the_team_lead_as_source() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        card = make_card()
        task = await _park(wait, clock, card)
        await asyncio.to_thread(wait.write, answered_part(card, by="team_lead", option="per_kwh"))
        await until(task.done)
        return task.result(), store

    answer, store = asyncio.run(go())
    assert (answer.answered_by, answer.option) == ("team_lead", "per_kwh")
    assert [e["data"]["answered_by"] for e in _answered(store)] == ["team_lead"]


def test_FR_HIL_10_an_unanswered_question_keeps_the_agent_waiting_until_its_deadline() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        card = make_card(timeout=3600)
        task = await _park(wait, clock, card)
        clock.advance(3599)
        await settle()
        return task.done(), len(_answered(store))

    done, written = asyncio.run(go())
    assert done is False, "1 s before created_at + timeout the agent is still waiting"
    assert written == 0, "and nothing was written for it"


def test_FR_HIL_10_timeout_applies_the_safe_default_posts_a_nudge_and_resumes_within_2_s() -> None:
    async def go():
        wait, slow, clock, store = _world()
        card = make_card(timeout=3600, safe_default="per_kwh")
        task = await _park(wait, clock, card)
        slow.delay_s = SLOW_WRITER_S
        started = time.perf_counter()
        clock.advance(3600)  # exactly the deadline, as API_FR_HIL_02's boundary
        await until(task.done)
        return task.result(), time.perf_counter() - started, store, card

    answer, elapsed, store, card = asyncio.run(go())

    assert answer == Answer(card_id=card["id"], option="per_kwh", answered_by="default")
    assert elapsed <= RESUME_BUDGET_S, f"the default must resume the agent in <= 2 s too, took {elapsed:.2f} s"
    (event,) = _answered(store)
    assert {k: v for k, v in event["data"].items() if k != "decision_id"} == {"answered_by": "default"}
    assert event["severity"] == "nudge", "EV-08, BQ-04: a default answer is posted as a Nudge"
    assert (event["actor"], event["target"]) == (DIRECTOR, LEAD), "the Director applies the default"
    assert (event["district"], event["vis"]) == (DISTRICT, [DISTRICT])


def test_FR_HIL_10_the_deadline_uses_the_cards_own_timeout_and_safe_default() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        card = make_card(timeout=90, safe_default="per_pack")
        task = await _park(wait, clock, card)
        clock.advance(89)
        await settle()
        before = task.done()
        clock.advance(1)
        await until(task.done)
        return before, task.result()

    before, answer = asyncio.run(go())
    assert before is False
    assert (answer.option, answer.answered_by) == ("per_pack", "default")


def test_FR_HIL_10_an_answer_before_the_deadline_cancels_the_default() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        card = make_card(timeout=3600)
        task = await _park(wait, clock, card)
        clock.advance(10)
        await asyncio.to_thread(wait.write, answered_part(card, option="per_pack"))
        await until(task.done)
        clock.advance(10_000)  # far past the deadline
        await settle()
        return task.result(), store

    answer, store = asyncio.run(go())
    assert (answer.option, answer.answered_by) == ("per_pack", "person")
    assert [e["data"]["answered_by"] for e in _answered(store)] == ["person"], "no default after a person answered"


def test_FR_HIL_10_a_late_answer_after_the_default_changes_nothing() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        card = make_card(timeout=60)
        task = await _park(wait, clock, card)
        clock.advance(60)
        await until(task.done)
        try:  # BQ-209: whether a late part raises is the builder's; it must not rewrite the outcome
            await asyncio.to_thread(wait.write, answered_part(card, option="per_pack", index=2))
        except Exception:  # noqa: S110
            pass
        await settle()
        return task.result(), store

    answer, store = asyncio.run(go())
    assert (answer.option, answer.answered_by) == ("per_kwh", "default"), "the first resolution wins"
    assert [e["data"]["answered_by"] for e in _answered(store)] == ["default"], "one question.answered per card"


def test_FR_HIL_10_the_api_timeout_part_resumes_with_the_safe_default_and_the_harness_adds_none() -> None:
    """`CardStore.tick()` may time a card out first and hand the harness its own default part (nudge)."""

    async def go():
        wait, _slow, clock, store = _world()
        card = make_card(timeout=3600, safe_default="per_kwh")
        task = await _park(wait, clock, card)
        part = answered_part(card, by="default", option=None, severity="nudge")
        await asyncio.to_thread(wait.write, part)
        await until(task.done)
        clock.advance(3600)
        await settle()
        return task.result(), store, part

    answer, store, part = asyncio.run(go())
    assert (answer.option, answer.answered_by) == ("per_kwh", "default")
    (event,) = _answered(store)
    assert (event["id"], event["severity"]) == (part["event_id"], "nudge")


def test_FR_HIL_10_an_answer_resumes_only_the_agent_waiting_on_that_card() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        first, second = make_card(1), make_card(2)
        task_1 = asyncio.ensure_future(wait.wait_for(first, lead=LEAD, director=DIRECTOR, district=DISTRICT))
        task_2 = asyncio.ensure_future(wait.wait_for(second, lead=LEAD, director=DIRECTOR, district=DISTRICT))
        await until(lambda: clock.pending_sleepers() >= 2)
        await asyncio.to_thread(wait.write, answered_part(second, option="per_pack", index=2))
        await until(task_2.done)
        await settle()
        waiting_1 = not task_1.done()
        await asyncio.to_thread(wait.write, answered_part(first, option="per_kwh", index=1))
        await until(task_1.done)
        return waiting_1, task_1.result(), task_2.result(), first, second

    waiting_1, answer_1, answer_2, first, second = asyncio.run(go())
    assert waiting_1, "answering card 2 must not resume the agent waiting on card 1"
    assert (answer_1.card_id, answer_1.option) == (first["id"], "per_kwh")
    assert (answer_2.card_id, answer_2.option) == (second["id"], "per_pack")


def test_FR_HIL_10_an_identical_resend_writes_one_event_and_resumes_once() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        card = make_card()
        task = await _park(wait, clock, card)
        part = answered_part(card, option="per_pack")
        await asyncio.to_thread(wait.write, part)
        await asyncio.to_thread(wait.write, dict(part))  # CardStore resends after a write that raised
        await until(task.done)
        await settle()
        return task.result(), store

    answer, store = asyncio.run(go())
    assert answer.option == "per_pack"
    assert len(_answered(store)) == 1


def test_FR_HIL_10_an_answer_for_a_card_nobody_waits_on_is_still_recorded_and_resumes_nobody() -> None:
    async def go():
        wait, _slow, clock, store = _world()
        waiting, other = make_card(1), make_card(2)
        task = await _park(wait, clock, waiting)
        await asyncio.to_thread(wait.write, answered_part(other, option="per_pack", index=2))
        await settle()
        return task.done(), store, other

    done, store, other = asyncio.run(go())
    assert done is False
    (event,) = _answered(store)
    assert event["data"]["answered_by"] == "person", "a person's answer is never dropped (BQ-209)"


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    steps=st.lists(
        st.one_of(
            st.tuples(
                st.just("answer"), st.sampled_from(["per_kwh", "per_pack"]), st.sampled_from(["person", "team_lead"])
            ),
            st.tuples(st.just("advance"), st.integers(min_value=0, max_value=2000), st.just("")),
        ),
        max_size=8,
    )
)
def test_FR_HIL_10_property_one_resolution_one_resume_first_one_wins(steps) -> None:
    """Any interleaving of answers and clock moves: exactly one question.answered per card, one resume, the first
    of (answer, deadline) wins, the option is one of the card's, and `seq` is strictly increasing."""

    async def go():
        wait, _slow, clock, store = _world()
        card = make_card(timeout=3600)
        task = await _park(wait, clock, card)
        elapsed, winner = 0, None
        for index, (kind, a, b) in enumerate(steps):
            if kind == "advance":
                clock.advance(a)
                elapsed += a
                if elapsed >= 3600 and winner is None:
                    winner = ("per_kwh", "default")
            else:
                if winner is None:
                    winner = (a, b)
                try:
                    wait.write(answered_part(card, by=b, option=a, index=index + 1))
                except Exception:  # noqa: S110  a late part may raise; it must not change the outcome
                    pass
            await settle()
        if winner is None:
            clock.advance(4000)
            winner = ("per_kwh", "default")
        await until(task.done)
        return task.result(), winner, store, card

    answer, winner, store, card = asyncio.run(go())
    assert (answer.option, answer.answered_by) == winner
    assert answer.option in {option["id"] for option in card["options"]}
    assert len(_answered(store)) == 1
    seqs = [e["seq"] for e in store.read_events("org_demo", WORLD)]
    assert seqs == sorted(set(seqs))
