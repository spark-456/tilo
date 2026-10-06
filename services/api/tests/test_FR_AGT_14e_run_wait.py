"""FR-AGT-14e (design decision 2): the run's wait primitive, `tilo_api.runs.Run.wait_until_parked_or_done`.

A Cloud Tasks delivery must return when its run is finished OR parked at a person (a gate card or a question: a gate can
wait 24 h and must not hold a request), or at the in-request deadline. The smallest honest primitive on `Run`:

    run.wait_until_parked_or_done(timeout_s, *, clock=time.monotonic, poll_s=0.25) -> "done" | "parked" | "timeout"

"done": the run's thread has ended (completed, failed, paused: any way out). "parked": the run is blocked on a person
(its gate card, or a question wait) and nothing it can do goes on. "timeout": `timeout_s` of `clock()` passed first
(a fake clock moves a test past a 25 minute deadline at once; `poll_s` is how often the wait looks at it, so a test
passes a tiny one). Interactive runs behave exactly as before. API_FR_AGT_14e.md; rig: the CL-INT-2 `RunFlow`.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from _agt05_lib import ASK, CLEAR, build_ask_flow, needs_you_cards, start_and_approve, tasks_provider
from _clint2_lib import wait_for


class TickingClock:
    """A monotonic clock that jumps `step` seconds every time it is read: the deadline passes with no real waiting."""

    def __init__(self, step: float) -> None:
        self.now, self.step, self.reads = 0.0, step, 0
        self._lock = threading.Lock()

    def __call__(self) -> float:
        with self._lock:
            self.now += self.step
            self.reads += 1
            return self.now


def run_of(rf: Any) -> Any:
    return rf.store.runs[rf.world_id]


def test_FR_AGT_14e_the_run_has_the_wait_primitive_and_nothing_else_changed_for_it(run_flow) -> None:
    from tilo_api import runs

    assert callable(getattr(runs.Run, "wait_until_parked_or_done", None))
    run_flow.run_to_gate()  # an interactive run still reaches its gate and waits, exactly as before
    assert run_flow.events("world.started") and not run_flow.events("world.completed")


def test_FR_AGT_14e_a_run_at_its_gate_is_parked_and_a_finished_run_is_done(run_flow) -> None:
    _requested, card = run_flow.run_to_gate()
    run = run_of(run_flow)
    started = time.monotonic()
    assert run.wait_until_parked_or_done(30.0) == "parked"  # it does not hold the caller for the gate's 24 hours
    assert time.monotonic() - started < 10
    assert run_flow.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    assert run.wait_until_parked_or_done(30.0) == "done"  # the thread ended
    assert run.wait_until_parked_or_done(0.0) == "done"  # and asking again does not wait


def test_FR_AGT_14e_a_run_that_is_working_is_neither_parked_nor_done_until_the_deadline(run_flow) -> None:
    run_flow.runner.block_on = "U1"
    run_flow.start()
    assert run_flow.approve().status_code == 200
    assert run_flow.runner.entered.wait(timeout=10), "the unit never started"
    run = run_of(run_flow)
    assert run.wait_until_parked_or_done(0.2) == "timeout"
    clock = TickingClock(step=600.0)  # 25 minutes pass in three reads
    started = time.monotonic()
    assert run.wait_until_parked_or_done(25 * 60, clock=clock, poll_s=0.001) == "timeout"
    assert time.monotonic() - started < 10, "a fake clock must not cost real time"
    assert clock.reads >= 2
    assert not run_flow.events("approval.requested") and not run_flow.events("world.completed")
    run_flow.runner.release.set()  # it was only slow: the same run goes on to its gate
    wait_for(lambda: run_flow.events("approval.requested"), what="the gate")
    assert run.wait_until_parked_or_done(30.0) == "parked"


def test_FR_AGT_14e_a_run_that_fails_is_done(run_flow) -> None:
    run_flow.compile_mode = "raise"  # the Director cannot plan: the run records world.failed and ends
    run_flow.start()
    assert run_flow.approve().status_code == 200
    assert run_of(run_flow).wait_until_parked_or_done(30.0) == "done"
    assert run_flow.events("world.failed")


def test_FR_AGT_14e_a_paused_world_ends_its_run_and_the_wait_says_done(run_flow) -> None:
    run_flow.run_to_gate()
    run = run_of(run_flow)
    assert run.wait_until_parked_or_done(30.0) == "parked"
    assert run_flow.pause().status_code == 200
    assert run.wait_until_parked_or_done(30.0) == "done"  # Pause all is final for the run (BQ-90)


@pytest.fixture
def asking(repo_root):
    flows = []

    def build():
        rf = build_ask_flow(repo_root, tasks_provider(ASK, *CLEAR[1:]), independent=True)
        flows.append(rf)
        start_and_approve(rf)
        wait_for(lambda: rf.events("question.routed"), what="question.routed")
        rf.quiet_stream()
        return rf

    yield build
    for rf in flows:
        rf.close()


def test_FR_AGT_14e_a_run_waiting_on_a_question_is_parked_until_it_is_answered(asking) -> None:
    rf = asking()
    (card,) = needs_you_cards(rf)
    run = run_of(rf)
    assert run.wait_until_parked_or_done(30.0) == "parked"  # the other units are done; only a person can go on
    response = rf.answer(card["id"], card["options"][0]["id"])
    assert response.status_code == 200, response.text
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    assert run.wait_until_parked_or_done(30.0) == "done"
