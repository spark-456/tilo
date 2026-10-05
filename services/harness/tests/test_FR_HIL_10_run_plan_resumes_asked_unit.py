"""FR-HIL-10 (PRD 10.2 "Needs you: That branch waits", 10.6, 8.3) through `run_plan(..., must_ask=...,
question_wait=...)`.

Given a plan whose unit U1 must ask, When the question is routed Then U1 waits (its work has not started) while
the other units go on and without holding a `max_specialists` slot; When the answer arrives Then U1's work runs
within 2.0 s with the answer in its context, its dependants follow, and `run_plan` returns; When nobody answers
by the card's deadline Then U1 runs with the card's safe default. Without `question_wait`, FR-AGT-05's
park-and-return (BQ-201) is unchanged. Interface: `hil_wait_support.py`; defaults BQ-207..BQ-209.
"""

from __future__ import annotations

import asyncio
import time

from agt_support import (
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from hil_wait_support import (
    DISTRICT,
    RESUME_BUDGET_S,
    WORLD,
    AnswerRunner,
    AskingMustAsk,
    FakeAsyncClock,
    answered_part,
    events_of,
    layout,
    settle,
    until,
)
from tilo_harness.executor import run_plan
from tilo_harness.question_wait import Answer, QuestionWait


def _setup(tmp_path, *, max_specialists: int = 3, with_dependant: bool = False):
    units = [build_unit("U1"), build_unit("U2")]
    if with_dependant:
        units.append(build_unit("U3", depends_on=["U1"]))
    config = load_config_sync(
        write_agents_config(tmp_path / "agents.yaml", limits={"max_specialists": max_specialists})
    )
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout(), world_id=WORLD)
    clock = FakeAsyncClock()

    def start(*, question_wait: bool = True):
        wait = QuestionWait(writer, clock=clock)
        must_ask = AskingMustAsk({"U1"})
        runner = AnswerRunner()
        kwargs = {"must_ask": must_ask, **({"question_wait": wait} if question_wait else {})}
        run = asyncio.ensure_future(
            run_plan(build_plan(units), layout(), writer=writer, config=config, skills=skills, runner=runner, **kwargs)
        )
        return run, wait, must_ask, runner

    return start, store, clock


async def _until_asked(store, runner, clock, *, clear_unit_ran: bool = True) -> None:
    await until(lambda: bool(events_of(store, "question.routed")) and (not clear_unit_ran or "U2" in runner.started))
    await settle()


def test_FR_HIL_10_run_plan_resumes_the_asked_unit_within_2_s_of_the_answer(tmp_path) -> None:
    start, store, clock = _setup(tmp_path, with_dependant=True)

    async def go():
        run, wait, must_ask, runner = start()
        await _until_asked(store, runner, clock)
        waiting = ("U1" not in runner.runs, not run.done())
        card = must_ask.cards["U1"]
        part = answered_part(card, option="per_pack")
        t0 = time.perf_counter()
        await asyncio.to_thread(wait.write, part)
        await until(lambda: "U1" in runner.started)
        resumed_in = runner.started["U1"] - t0
        result = await asyncio.wait_for(run, timeout=20)
        return waiting, resumed_in, result, runner, card

    waiting, resumed_in, result, runner, card = asyncio.run(go())

    assert waiting == (True, True), "while it waits the asked unit has not started and run_plan has not returned"
    assert resumed_in <= RESUME_BUDGET_S, (
        f"FR-HIL-10: answering must resume the agent in <= 2 s, took {resumed_in:.2f} s"
    )
    assert runner.answers["U1"] == Answer(card_id=card["id"], option="per_pack", answered_by="person")
    assert runner.answers["U2"] is None, "a unit that never asked carries no answer"
    assert runner.runs.count("U1") == 1, "the unit's work runs exactly once"
    assert runner.runs.index("U3") > runner.runs.index("U1"), "a dependant starts only after the unit has finished"
    assert result.outcomes["U1"].success and not result.failed and not result.skipped

    events = events_of(store, "question.answered") + events_of(store, "question.routed")
    routed, answered = events_of(store, "question.routed")[0], events_of(store, "question.answered")[0]
    assert len(events) == 2 and routed["seq"] < answered["seq"]
    worker = next(e["target"] for e in events_of(store, "agent.assigned") if e["data"]["unit"] == "U1")
    handoff = next(e for e in events_of(store, "agent.handoff") if e["data"]["envelope"]["from"] == worker)
    assert answered["seq"] < handoff["seq"], "the unit hands over only after it was answered"


def test_FR_HIL_10_run_plan_runs_the_asked_unit_with_the_safe_default_at_the_deadline(tmp_path) -> None:
    start, store, clock = _setup(tmp_path)

    async def go():
        run, _wait, must_ask, runner = start()
        await _until_asked(store, runner, clock)
        await until(lambda: clock.pending_sleepers() >= 1)
        clock.advance(3599)
        await settle()
        before = "U1" in runner.runs
        t0 = time.perf_counter()
        clock.advance(1)
        await until(lambda: "U1" in runner.started)
        resumed_in = runner.started["U1"] - t0
        await asyncio.wait_for(run, timeout=20)
        return before, resumed_in, runner, must_ask.cards["U1"]

    before, resumed_in, runner, card = asyncio.run(go())

    assert before is False, "1 s before the deadline the unit is still waiting"
    assert resumed_in <= RESUME_BUDGET_S
    assert runner.answers["U1"] == Answer(card_id=card["id"], option=card["safe_default"], answered_by="default")
    (answered,) = events_of(store, "question.answered")
    assert (answered["data"]["answered_by"], answered["severity"]) == ("default", "nudge")


def test_FR_HIL_10_a_waiting_unit_holds_no_specialist_slot(tmp_path) -> None:
    """max_specialists = 1: if U1 kept its slot while it waited, U2 could never run and the plan would deadlock."""
    start, store, clock = _setup(tmp_path, max_specialists=1)

    async def go():
        run, wait, must_ask, runner = start()
        await _until_asked(store, runner, clock)  # U2 must have run with U1 still waiting
        still_waiting = not run.done() and "U1" not in runner.runs
        await asyncio.to_thread(wait.write, answered_part(must_ask.cards["U1"], option="per_kwh"))
        result = await asyncio.wait_for(run, timeout=20)
        return still_waiting, runner, result

    still_waiting, runner, result = asyncio.run(go())
    assert still_waiting
    assert runner.runs == ["U2", "U1"] and result.outcomes["U1"].success


def test_FR_HIL_10_without_question_wait_the_asked_unit_stays_parked_and_the_run_returns(tmp_path) -> None:
    start, store, clock = _setup(tmp_path)

    async def go():
        run, _wait, _must_ask, runner = start(question_wait=False)
        await asyncio.wait_for(run, timeout=20)
        return runner

    runner = asyncio.run(go())
    assert runner.runs == ["U2"], "FR-AGT-05 / BQ-201: the asked unit's work never starts and the run returns"
    assert len(events_of(store, "question.routed")) == 1
    assert events_of(store, "question.answered") == [], f"nothing waits, so nothing is answered ({DISTRICT})"
