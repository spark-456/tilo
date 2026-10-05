"""FR-HIL-10, issue #338 (Opus review r1 of PR #359; PRD 10.3 "Every card has a timeout and a safe default", 8.3):
a question's derived event id carries no option and the event's content holds only `answered_by`. So after answer A
commits and then raises (its caller saw a failure), a later answer B with the SAME answered_by and ANOTHER option meets
an event the writer cannot tell from a resend. The unit must only ever resume with the option of the attempt that really
committed; a never-committed option must never drive a unit (a held rule step must stay held).

Pinned: (1) B (same answered_by, other option) after A's commit-then-raise is refused (AlreadyAnswered), writes nothing,
and the unit resumes at once with A's option; (2) the same when B's own write would have failed, so B never reaches the
deadline's bookkeeping; (3) when A did not commit, B is an ordinary first answer and the unit resumes with B's option;
(4) A fails (nothing committed), B fails too, the deadline applies the safe default and nothing else is written; (5) an
identical resend of A still succeeds; (6) a deadline default that committed and then raised counts as written.
The writer double (`claim_race_support.ScriptedWriter`) offers `committed(event_id)`, the lookup `QuestionWait` asks.
"""

from __future__ import annotations

import asyncio

from claim_race_support import SAFE_DEFAULT, InjectedFailure, attempt, finished, park, settle, world
from hil_wait_support import answered_part
from tilo_harness.question_wait import AlreadyAnswered, Answer


def _part(card, option, by="team_lead"):
    return answered_part(card, by=by, option=option, index=1)


def test_FR_HIL_10_same_answerer_other_option_after_a_commit_then_raise_is_refused_and_the_unit_resumes_with_a():
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        writer.plan("commit+raise")
        a = await asyncio.to_thread(attempt, wait.write, _part(card, "per_pack"))
        b = await asyncio.to_thread(attempt, wait.write, _part(card, "per_kwh"))  # the writer would take it as a resend
        done = await finished(task)
        clock.advance(10_000)
        await settle()
        return a, b, done, task, writer, card

    a, b, done, task, writer, card = asyncio.run(go())

    assert isinstance(a, InjectedFailure) and isinstance(b, AlreadyAnswered)
    assert done and task.result() == Answer(card["id"], "per_pack", "team_lead"), "A's option, never B's"
    assert [e["data"]["answered_by"] for e in writer.answered()] == ["team_lead"], "one event, and no default later"
    assert len(writer.calls) == 1, "B was refused without a write"


def test_FR_HIL_10_a_commit_then_raise_then_another_option_that_would_have_failed_still_resumes_with_the_first():
    async def go():
        wait, writer, clock, card = world(timeout=3)
        task = await park(wait, clock, card)
        writer.plan("commit+raise", "raise")
        a = await asyncio.to_thread(attempt, wait.write, _part(card, "per_pack"))
        b = await asyncio.to_thread(attempt, wait.write, _part(card, "per_kwh"))
        await settle()
        clock.advance(4000)  # the deadline
        done = await finished(task)
        return a, b, done, task, writer, card

    a, b, done, task, writer, card = asyncio.run(go())

    assert isinstance(a, InjectedFailure) and isinstance(b, AlreadyAnswered)
    assert done, "the unit resumed with the committed answer"
    assert task.result() == Answer(card["id"], "per_pack", "team_lead"), "the held step must not run on B's option"
    assert [e["data"]["answered_by"] for e in writer.answered()] == ["team_lead"]


def test_FR_HIL_10_two_failed_answers_with_different_options_then_the_deadline_applies_the_safe_default():
    async def go():
        wait, writer, clock, card = world(timeout=3)
        task = await park(wait, clock, card)
        writer.plan("raise", "raise")
        a = await asyncio.to_thread(attempt, wait.write, _part(card, "per_pack"))
        b = await asyncio.to_thread(attempt, wait.write, _part(card, "per_kwh"))
        await settle()
        clock.advance(4000)
        done = await finished(task)
        return a, b, done, task, writer, card

    a, b, done, task, writer, card = asyncio.run(go())

    assert isinstance(a, InjectedFailure) and isinstance(b, InjectedFailure), "nothing committed: both may retry"
    assert done and task.result() == Answer(card["id"], SAFE_DEFAULT, "default")
    assert [e["data"]["answered_by"] for e in writer.answered()] == ["default"]


def test_FR_HIL_10_a_failed_answer_then_another_option_that_commits_resumes_with_the_option_that_committed():
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        writer.plan("raise")
        a = await asyncio.to_thread(attempt, wait.write, _part(card, "per_pack"))
        b = await asyncio.to_thread(attempt, wait.write, _part(card, "per_kwh"))
        done = await finished(task)
        return a, b, done, task, writer, card

    a, b, done, task, writer, card = asyncio.run(go())

    assert isinstance(a, InjectedFailure) and b is None
    assert done and task.result() == Answer(card["id"], "per_kwh", "team_lead"), "A never committed: B is the answer"
    assert [e["data"]["answered_by"] for e in writer.answered()] == ["team_lead"]


def test_FR_HIL_10_an_identical_resend_after_a_commit_then_raise_still_succeeds_with_its_own_option():
    async def go():
        wait, writer, clock, card = world()
        task = await park(wait, clock, card)
        writer.plan("commit+raise")
        a = await asyncio.to_thread(attempt, wait.write, _part(card, "per_pack"))
        b = await asyncio.to_thread(attempt, wait.write, _part(card, "per_pack"))
        done = await finished(task)
        return a, b, done, task, writer, card

    a, b, done, task, writer, card = asyncio.run(go())

    assert isinstance(a, InjectedFailure) and b is None
    assert done and task.result() == Answer(card["id"], "per_pack", "team_lead")
    assert len(writer.answered()) == 1


def test_FR_HIL_10_a_deadline_default_that_committed_and_then_raised_counts_as_written():
    async def go():
        wait, writer, clock, card = world(timeout=3)
        task = await park(wait, clock, card)
        writer.plan("commit+raise")
        clock.advance(4000)
        done = await finished(task)
        return done, task, writer, card

    done, task, writer, card = asyncio.run(go())

    assert done and not task.exception(), "the default is on the record: the unit is not handed the error"
    assert task.result() == Answer(card["id"], SAFE_DEFAULT, "default")
    assert [e["data"]["answered_by"] for e in writer.answered()] == ["default"]
