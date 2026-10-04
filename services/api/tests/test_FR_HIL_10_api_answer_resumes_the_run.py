"""FR-HIL-10 through the API (PRD 10.2 "Needs you: that branch waits", 10.6 "answering resumes the agent in <= 2 s",
8.3), on top of FR-AGT-05's wiring (`test_FR_AGT_05_api_must_ask_wiring.py`): a unit that asked is not parked for good.
It waits for its answer; answering the card over the existing cards route writes `question.answered`, and within 2.0 s
the unit's work runs once with the answer in its context, the units that depended on it follow, and the run completes.

These tests need the harness half of FR-HIL-10, `tilo_harness.question_wait.QuestionWait` (interface pinned in branch
tests/FR-HIL-10-harness-resume, `services/harness/tests/hil_wait_support.py`; defaults BQ-207..BQ-209), and the API
passing `question_wait=` to `run_plan`. Scripted models and runner, the in-process app: no timer, no server, no network.
"""

from __future__ import annotations

import time

import pytest
from _agt05_lib import (
    ASK,
    CLEAR,
    RESUME_BUDGET_S,
    build_ask_flow,
    needs_you_cards,
    start_and_approve,
    tasks_provider,
    worker_of,
)
from _clint2_lib import wait_for

TERMINAL = ("world.completed", "world.failed")


@pytest.fixture()
def waiting(repo_root):
    """Builds a run whose U1 asked (U2 and U3 do not depend on it) and returns (RunFlow, the needs_you card). A
    builder, not a ready run, so a run that never asks fails the test body (not its setup)."""
    flows = []

    def build():
        rf = build_ask_flow(repo_root, tasks_provider(ASK, *CLEAR[1:]), independent=True)
        flows.append(rf)
        start_and_approve(rf)
        wait_for(lambda: rf.events("question.routed"), what="question.routed")
        rf.quiet_stream()
        (card,) = needs_you_cards(rf)
        return rf, card

    yield build
    for rf in flows:
        rf.close()


def test_FR_HIL_10_api_the_harness_question_wait_module_exists():
    from tilo_harness.question_wait import Answer, QuestionWait  # noqa: PLC0415

    assert Answer and QuestionWait


def test_FR_HIL_10_api_a_waiting_unit_holds_nothing_back_and_the_run_waits_for_its_answer(waiting):
    rf, _card = waiting()

    assert {"U2", "U3"} <= set(rf.runner.ran), "the units that do not depend on the asked unit go on (BQ-209)"
    assert "U1" not in rf.runner.ran, "the asked unit has not started"
    assert not [e for e in rf.stream() if e["type"] in TERMINAL], "the run is waiting, not finished"
    assert rf.events("question.answered") == []


def test_FR_HIL_10_api_answering_the_card_emits_question_answered_and_resumes_the_unit_within_2_s(waiting):
    rf, card = waiting()
    chosen = card["options"][1]  # the second label of the recorded reply, not the suggested one

    t0 = time.monotonic()
    response = rf.answer(card["id"], chosen["id"])
    assert response.status_code == 200 and response.json() == {"outcome": "answered"}, response.text
    wait_for(lambda: "U1" in rf.runner.started_at, timeout=RESUME_BUDGET_S + 1, what="U1 to resume")
    resumed_in = rf.runner.started_at["U1"] - t0

    assert resumed_in <= RESUME_BUDGET_S, (
        f"FR-HIL-10: answering must resume the agent in <= 2 s, took {resumed_in:.2f} s"
    )
    (answered,) = rf.events("question.answered")
    assert answered["data"]["answered_by"] == "person"
    assert answered["vis"] == [answered["district"]], "the answer is the asked district's event, never widened"
    answer = rf.runner.answers["U1"]
    assert (answer.card_id, answer.option, answer.answered_by) == (card["id"], chosen["id"], "person")
    assert all(rf.runner.answers[u] is None for u in ("U2", "U3")), "a unit that never asked carries no answer"
    assert rf.runner.ran.count("U1") == 1, "the unit's work runs exactly once"

    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    events = rf.quiet_stream()
    types = [e["type"] for e in events]
    assert types.count("world.completed") == 1 and "world.failed" not in types
    routed = next(e for e in events if e["type"] == "question.routed")
    worker = worker_of(rf, "U1")
    working = next(e for e in events if e["type"] == "agent.working" and e["data"]["unit"] == "U1")
    handoff = next(e for e in events if e["type"] == "agent.handoff" and e["actor"] == worker)
    assert routed["seq"] < answered["seq"] < working["seq"] < handoff["seq"], (
        "it works and hands over only once answered"
    )
    assert [c for c in rf.cards().json() if c["id"] == card["id"]] == [], "an answered card leaves the open list"
    assert rf.delivery().status_code == 200


def test_FR_HIL_10_api_a_second_answer_changes_nothing_and_resumes_nobody_twice(waiting):
    rf, card = waiting()
    option = card["options"][0]["id"]

    first = rf.answer(card["id"], option)
    assert first.status_code == 200, first.text
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    again = rf.answer(card["id"], card["options"][1]["id"])

    assert again.status_code in (400, 404, 409), again.text  # an answered card is no longer open: the first answer won
    rf.quiet_stream()
    assert len(rf.events("question.answered")) == 1
    assert rf.runner.ran.count("U1") == 1 and rf.runner.answers["U1"].option == option
    assert len(rf.events("world.completed")) == 1
