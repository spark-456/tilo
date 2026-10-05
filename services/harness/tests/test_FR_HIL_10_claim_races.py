"""FR-HIL-10 claim races in `QuestionWait` (issue #338 item 2; PRD 10.2, 10.3, 10.6; interface in
`claim_race_support.py`): "answering resumes the agent" and "every card has a timeout and a safe default; the
Director applies the default" must both hold when a writer fails at the wrong moment.

  B1  A person's answer claims the card and its write raises (nothing committed): the card is not stuck. Whether the
      deadline is still ahead, or already passed while the write was in flight, the Director's safe default is written
      once and the waiter resumes with it; the same answer sent again succeeds.
  B2  Commit-then-raise of answer A, then a different answer B: the writer raises `AlreadyCommitted` for B, `write(B)`
      raises `AlreadyAnswered`, and the waiter resumes at once with A (option and `answered_by`); one event, no default.
      With no failed attempt known, the committed event's `answered_by` and the card's safe default resolve it.
  B3  Commit-then-raise of A, then the deadline: the default (same event id) meets `AlreadyCommitted` and the waiter
      resumes with A; no second `question.answered`.

PRD gaps resolved: none beyond BQ-207..BQ-209 (`hil_wait_support.py`). The one choice here: after several failed
attempts, the committed event's `answered_by` picks which attempt's option the waiter resumes with (the option is not
event data, BQ-207), so QuestionWait must remember each failed attempt by who made it.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from claim_race_support import (
    CARD_CREATED,
    OPTION_OF,
    SAFE_DEFAULT,
    InjectedFailure,
    attempt,
    finished,
    park,
    settle,
    world,
)
from hil_wait_support import RESUME_BUDGET_S, answered_part
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_harness.question_wait import AlreadyAnswered, Answer


def _answer(card, *, by="person", option="per_pack"):
    """The part for an answer. Every answer to one card carries ONE event id (CardStore derives it from the card, not
    from the option), so A and B below collide on purpose."""
    return answered_part(card, by=by, option=option, index=1)


def test_FR_HIL_10_already_committed_is_an_exception_of_question_wait() -> None:
    from tilo_harness import question_wait  # noqa: PLC0415

    assert issubclass(question_wait.AlreadyCommitted, Exception)
    committed = {"id": "x", "data": {"answered_by": "person"}}
    assert question_wait.AlreadyCommitted(committed).args[0] == committed


def test_FR_HIL_10_failed_answer_before_the_deadline_leaves_the_default_to_fire_once() -> None:
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        writer.plan("raise")
        error = await asyncio.to_thread(attempt, wait.write, _answer(card))
        await settle()
        waiting = not task.done()
        clock.advance(3600)  # nobody answered again: the deadline fires normally
        done = await finished(task)
        clock.advance(10_000)
        await settle()
        return error, waiting, done, task, writer, card

    error, waiting, done, task, writer, card = asyncio.run(go())

    assert isinstance(error, InjectedFailure), "the caller sees the failure of its own answer"
    assert waiting, "a failed answer resolves nothing: the unit still waits"
    assert done, "the deadline default resumes the unit"
    assert task.result() == Answer(card["id"], SAFE_DEFAULT, "default")
    (event,) = writer.answered()
    assert event["data"] == {"answered_by": "default"} and event["severity"] == "nudge"


def test_FR_HIL_10_failed_answer_after_the_deadline_saw_the_claim_still_gets_the_default() -> None:
    """The deadline task wakes while the person's write is in flight, sees the claim and stands down; then the write
    raises. Nobody answers again and the clock does not move: the card must not be stuck."""

    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        writer.plan("block+raise")
        in_flight = asyncio.ensure_future(asyncio.to_thread(attempt, wait.write, _answer(card)))
        deadline_at = time.perf_counter() + 5
        while not writer.entered.is_set() and time.perf_counter() < deadline_at:
            await asyncio.sleep(0.001)
        assert writer.entered.is_set(), "the answer's emit is in flight"
        clock.advance(3600)  # the deadline passes while the answer's emit is blocked
        await settle()
        resolved_early = task.done()
        writer.release()  # ... then the emit raises
        error = await in_flight
        done = await finished(task)
        await settle()
        return error, resolved_early, done, task, writer, card

    error, resolved_early, done, task, writer, card = asyncio.run(go())

    assert isinstance(error, InjectedFailure)
    assert not resolved_early, "the in-flight answer, not the deadline, owned the card meanwhile"
    assert done, "the deadline already passed and nobody answers again: the default is written now, not never"
    assert task.result() == Answer(card["id"], SAFE_DEFAULT, "default")
    (event,) = writer.answered()
    assert event["data"] == {"answered_by": "default"}, "one question.answered, the Director's safe default"


def test_FR_HIL_10_the_same_answer_sent_again_after_a_failure_succeeds_and_resumes_with_its_option() -> None:
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        part = _answer(card, option="per_pack")
        writer.plan("raise")
        first = await asyncio.to_thread(attempt, wait.write, part)
        second = await asyncio.to_thread(attempt, wait.write, dict(part))
        done = await finished(task, within_s=RESUME_BUDGET_S)
        clock.advance(10_000)
        await settle()
        return first, second, done, task, writer, card, clock

    first, second, done, task, writer, card, _clock = asyncio.run(go())

    assert isinstance(first, InjectedFailure) and second is None
    assert done and task.result() == Answer(card["id"], "per_pack", "person")
    assert [e["data"]["answered_by"] for e in writer.answered()] == ["person"], "no default after the answer landed"


def test_FR_HIL_10_commit_then_raise_then_another_answer_resumes_with_the_committed_one() -> None:
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        a = _answer(card, by="person", option="per_pack")
        b = _answer(card, by="team_lead", option="per_kwh")
        assert a["event_id"] == b["event_id"] and a["data"] != b["data"], "same derived id, other content"
        writer.plan("commit+raise")
        error_a = await asyncio.to_thread(attempt, wait.write, a)
        started = time.perf_counter()
        error_b = await asyncio.to_thread(attempt, wait.write, b)  # the writer raises AlreadyCommitted for B
        done = await finished(task, within_s=RESUME_BUDGET_S)
        elapsed = time.perf_counter() - started
        resumed_at = clock.now()
        clock.advance(10_000)  # far past the deadline
        await settle()
        return error_a, error_b, done, elapsed, resumed_at, task, writer, card

    error_a, error_b, done, elapsed, resumed_at, task, writer, card = asyncio.run(go())

    assert isinstance(error_a, InjectedFailure), "A's caller saw a failure although A was committed"
    assert isinstance(error_b, AlreadyAnswered), "the card is resolved: B is told it lost"
    assert done and elapsed <= RESUME_BUDGET_S, f"the unit resumes promptly (<= 2 s), took {elapsed:.2f} s"
    assert resumed_at == CARD_CREATED, "no timer produced this: the committed answer did"
    assert task.result() == Answer(card["id"], "per_pack", "person"), "it resumes with A's option and A's source"
    (event,) = writer.answered()
    assert event["data"] == {"answered_by": "person"}, "exactly one question.answered, A's, and no default later"


def test_FR_HIL_10_already_committed_with_no_known_attempt_resolves_with_the_safe_default_and_its_source() -> None:
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        part = _answer(card, by="person", option="per_pack")
        committed = writer.commit_directly(event_id=part["event_id"], by="team_lead")  # not by this QuestionWait
        error = await asyncio.to_thread(attempt, wait.write, part)
        done = await finished(task, within_s=RESUME_BUDGET_S)
        clock.advance(10_000)
        await settle()
        return error, done, task, writer, card, committed

    error, done, task, writer, card, committed = asyncio.run(go())

    assert isinstance(error, AlreadyAnswered)
    assert done, "a committed resolution resumes the waiter even though this process never made it"
    assert task.result() == Answer(card["id"], SAFE_DEFAULT, committed["data"]["answered_by"])
    assert writer.answered() == [committed], "nothing was written on top of it"


def test_FR_HIL_10_deadline_default_meeting_a_commit_then_raise_answer_resumes_with_that_answer() -> None:
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        writer.plan("commit+raise")
        error = await asyncio.to_thread(attempt, wait.write, _answer(card, by="person", option="per_pack"))
        await settle()
        waiting = not task.done()
        clock.advance(3600)  # the default is written now and finds A already committed under its event id
        done = await finished(task)
        clock.advance(10_000)
        await settle()
        return error, waiting, done, task, writer, card

    error, waiting, done, task, writer, card = asyncio.run(go())

    assert isinstance(error, InjectedFailure)
    assert waiting
    assert done, "the unit resumes at the deadline"
    assert task.result() == Answer(card["id"], "per_pack", "person"), "the committed answer wins, not the default"
    (event,) = writer.answered()
    assert event["data"] == {"answered_by": "person"}, "no second question.answered for the card"


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    steps=st.lists(
        st.one_of(
            st.tuples(
                st.just("answer"),
                st.sampled_from(["commit", "raise", "commit+raise"]),
                st.sampled_from(["person", "team_lead"]),
            ),
            st.tuples(st.just("advance"), st.integers(min_value=0, max_value=2000), st.just("")),
        ),
        max_size=7,
    )
)
def test_FR_HIL_10_property_one_committed_resolution_and_the_waiter_always_agrees_with_it(steps) -> None:
    """Any mix of answers (committed, failed, committed-then-failed; person or Team Lead) and clock moves: once the
    deadline has passed the waiter is always resumed, exactly one question.answered exists, and the waiter's answer is
    the one that was committed (its source from the event, its option from the attempt that made it)."""

    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        for kind, a, b in steps:
            if kind == "advance":
                clock.advance(a)
            else:
                writer.plan(a)
                attempt(wait.write, _answer(card, by=b, option=OPTION_OF[b]))
                writer._modes.clear()  # a mode an attempt never reached must not leak into the next write
            await settle()
        clock.advance(4000)  # whatever happened, the deadline has now passed
        done = await finished(task)
        await settle()
        return done, task, writer, card

    done, task, writer, card = asyncio.run(go())

    assert done, "the waiter is resumed once the deadline has passed, whatever failed on the way"
    (event,) = writer.answered()
    by = event["data"]["answered_by"]
    option = SAFE_DEFAULT if by == "default" else OPTION_OF[by]
    assert task.result() == Answer(card["id"], option, by), "the waiter resumes with what was committed"
    assert option in {o["id"] for o in card["options"]}
    assert [e["seq"] for e in writer.events] == sorted({e["seq"] for e in writer.events})


@pytest.mark.parametrize("mode", ["raise", "commit+raise"])
def test_FR_HIL_10_a_failed_answer_is_always_reported_to_its_caller(mode) -> None:
    async def go():
        wait, writer, clock, card = world()
        await park(wait, clock, card)
        writer.plan(mode)
        return await asyncio.to_thread(attempt, wait.write, _answer(card))

    assert isinstance(asyncio.run(go()), InjectedFailure), "the person is told their answer may not have landed"
