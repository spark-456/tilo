"""FR-AGT-05 + FR-HIL-10 (PRD 8.3, 10.2, 10.3), review of PR #336: a person's answer to a MODEL-raised sensitive_step
card only records a choice. The model's labels, their order and its `suggested` marker never authorise the step:
picking the suggested option (or the Director's default at the deadline) holds it; any other choice makes code raise
one more card, with words and order code owns, quoting the choice; only that card's "Prepare it" runs the unit.
An ambiguity or trade-off card keeps its earlier behaviour (any answer, the deadline default included, runs the unit).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from agt_must_ask_support import load_tasks
from hil_wait_support import WORLD, answered_part, events_of, settle, until
from test_FR_HIL_10_held_unit_stays_unrun import SEND_TITLE, _asked, _setup

MODEL_SENSITIVE = [t for t in load_tasks() if t.get("model_reply", {}).get("reason") == "sensitive_step"]
HOLD, PREPARE = "Hold this step", "Prepare it"  # the confirmation card's fixed words


def _reply(task, *, swapped: bool) -> dict:
    """The recorded reply, or the same reply with its options reversed and `suggested` pointing at the other one."""
    reply = dict(task["model_reply"])
    if swapped:
        reply["options"] = list(reversed(reply["options"]))
        reply["suggested"] = len(reply["options"]) - 1 - reply["suggested"]
    return reply


def _setup_for(tmp_path, reply):
    return _setup(tmp_path, actions=[], replies={SEND_TITLE: json.dumps(reply)})


def _assert_held(result, runner, store, *, answered):
    assert result.held == ["U1"] and "U2" in result.skipped and not result.failed
    assert runner.runs == ["U3"], "the held unit and its dependant never ran; the independent unit did"
    worker = next(e["target"] for e in events_of(store, "agent.assigned") if e["data"]["unit"] == "U1")
    types = [e["type"] for e in store.read_events("org_demo", WORLD) if worker in (e["actor"], e["target"])]
    assert "agent.working" not in types and "artifact.created" not in types and types[-1] == "agent.retired"
    assert len(events_of(store, "question.answered")) == answered


def test_FR_AGT_05_FR_HIL_10_the_recorded_sensitive_step_replies_are_the_three_pinned_ones() -> None:
    assert [t["id"] for t in MODEL_SENSITIVE] == ["ASK-10", "ASK-11", "ASK-12"]


@pytest.mark.parametrize("swapped", [False, True], ids=["as_recorded", "markers_swapped"])
@pytest.mark.parametrize("task", MODEL_SENSITIVE, ids=lambda t: t["id"])
def test_FR_AGT_05_FR_HIL_10_picking_the_suggested_option_holds_with_no_second_card(tmp_path, task, swapped) -> None:
    reply = _reply(task, swapped=swapped)

    async def go():
        run, wait, runner, cards, _clock, store = _setup_for(tmp_path, reply)
        card = await _asked(run, runner, cards)
        suggested = next(o["id"] for o in card["options"] if o["suggested"])
        await asyncio.to_thread(wait.write, answered_part(card, option=suggested))
        result = await asyncio.wait_for(run, 20)
        return result, runner, store, cards

    result, runner, store, cards = asyncio.run(go())
    _assert_held(result, runner, store, answered=1)
    assert len(cards) == 1


@pytest.mark.parametrize("swapped", [False, True], ids=["as_recorded", "markers_swapped"])
@pytest.mark.parametrize("task", MODEL_SENSITIVE, ids=lambda t: t["id"])
def test_FR_AGT_05_FR_HIL_10_another_choice_only_records_it_and_asks_once_more(tmp_path, task, swapped) -> None:
    reply = _reply(task, swapped=swapped)

    async def go(confirm_option):
        run, wait, runner, cards, _clock, store = _setup_for(tmp_path / confirm_option, reply)
        first = await _asked(run, runner, cards)
        other = next(o for o in first["options"] if not o["suggested"])
        await asyncio.to_thread(wait.write, answered_part(first, option=other["id"]))
        await until(lambda: len(cards) == 2)
        await settle()
        assert not run.done() and "U1" not in runner.runs, "the answer to the model's card ran nothing"
        second = cards[1]
        assert [o["label"] for o in second["options"]] == [HOLD, PREPARE] and second["safe_default"] == "o1"
        assert second["options"][0]["suggested"] and second["what_happened"].count(other["label"]) == 1
        await asyncio.to_thread(wait.write, answered_part(second, option=confirm_option, index=2))
        return await asyncio.wait_for(run, 20), runner, store, other

    result, runner, store, other = asyncio.run(go("o2"))
    assert runner.runs.count("U1") == 1 and not result.held and not result.skipped
    assert runner.answers["U1"].option == other["id"], "the runner gets the person's first choice"

    result, runner, store, _ = asyncio.run(go("o1"))
    _assert_held(result, runner, store, answered=2)


@pytest.mark.parametrize("swapped", [False, True], ids=["as_recorded", "markers_swapped"])
@pytest.mark.parametrize("task", MODEL_SENSITIVE, ids=lambda t: t["id"])
def test_FR_AGT_05_FR_HIL_10_the_deadline_default_holds_on_either_card(tmp_path, task, swapped) -> None:
    reply = _reply(task, swapped=swapped)

    async def first_card():
        run, _wait, runner, cards, clock, store = _setup_for(tmp_path / "a", reply)
        await _asked(run, runner, cards)
        await until(lambda: clock.pending_sleepers() >= 1)
        clock.advance(3600 + 5)
        return await asyncio.wait_for(run, 20), runner, store, cards

    result, runner, store, cards = asyncio.run(first_card())
    _assert_held(result, runner, store, answered=1)
    assert len(cards) == 1 and events_of(store, "question.answered")[0]["data"]["answered_by"] == "default"

    async def second_card():
        run, wait, runner, cards, clock, store = _setup_for(tmp_path / "b", reply)
        first = await _asked(run, runner, cards)
        other = next(o["id"] for o in first["options"] if not o["suggested"])
        await asyncio.to_thread(wait.write, answered_part(first, option=other))
        await until(lambda: len(cards) == 2)
        await until(lambda: clock.pending_sleepers() >= 1)
        clock.advance(3600 + 5)
        return await asyncio.wait_for(run, 20), runner, store

    result, runner, store = asyncio.run(second_card())
    _assert_held(result, runner, store, answered=2)
    assert events_of(store, "question.answered")[1]["data"]["answered_by"] == "default"


@pytest.mark.parametrize("task_id", ["ASK-06", "ASK-07"])
def test_FR_AGT_05_FR_HIL_10_ambiguity_and_trade_off_cards_still_run_on_the_deadline_default(tmp_path, task_id) -> None:
    task = next(t for t in load_tasks() if t["id"] == task_id)
    assert task["model_reply"]["reason"] in ("ambiguous_brief", "trade_off")

    async def go():
        run, _wait, runner, cards, clock, _store = _setup_for(tmp_path, task["model_reply"])
        await _asked(run, runner, cards)
        await until(lambda: clock.pending_sleepers() >= 1)
        clock.advance(3600 + 5)
        return await asyncio.wait_for(run, 20), runner, cards

    result, runner, cards = asyncio.run(go())
    assert runner.runs.count("U1") == 1 and not result.held and len(cards) == 1
