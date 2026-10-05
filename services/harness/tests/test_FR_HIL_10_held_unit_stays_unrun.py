"""FR-HIL-10 (PRD 10.2 "that branch waits", 10.3 "the Director applies the default", 8.3), review of PR #336: an
answer lets the asked unit run only if the HARNESS says so, from the Ask it raised (`Ask.runs`), never the runner or a
model. For a rule's card (sensitive_step, repeated_failure, unreadable reply) only its proceed option runs the unit;
Hold, Stop, Skip and the safe default at the deadline leave it unrun: no agent.working, no artifact, its dependents
skipped, the other units go on, and `run_plan` still returns. A model-written card runs the unit on a person's answer
(whatever option) and holds it on the Director's default. Interface: `hil_wait_support.py`; BQ-235.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
from agt_must_ask_support import load_tasks
from agt_scripted import ScriptedProvider, role_providers
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
    OWNER,
    WORLD,
    AnswerRunner,
    FakeAsyncClock,
    answered_part,
    events_of,
    layout,
    settle,
    until,
)
from tilo_harness.executor import run_plan
from tilo_harness.must_ask import MustAsk
from tilo_harness.question_wait import QuestionWait

SEND_TITLE = "Send the supplier summary"
ASK_TASK = next(task for task in load_tasks() if task["id"] == "ASK-06")
CLEAR = json.dumps({"ask": False})


def _setup(tmp_path, *, actions, replies=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout(), world_id=WORLD)
    clock = FakeAsyncClock(start=datetime.now(UTC))  # the card's deadline is writer.now() + 1 h
    wait = QuestionWait(writer, clock=clock)
    cards: list[dict] = []
    specialist = ScriptedProvider(replies or {}, default=CLEAR)
    must_ask = MustAsk(
        role_providers(specialist=specialist), config=config, card_sink=cards.append, owner=OWNER,
        covered_actions=frozenset(),
    )  # fmt: skip
    first = build_unit("U1", title=SEND_TITLE)
    first["actions"] = list(actions)
    plan = build_plan([first, build_unit("U2", depends_on=["U1"]), build_unit("U3")])
    runner = AnswerRunner()
    run = asyncio.ensure_future(
        run_plan(
            plan,
            layout(),
            writer=writer,
            config=config,
            skills=skills,
            runner=runner,
            must_ask=must_ask,
            question_wait=wait,
        )  # fmt: skip
    )
    return run, wait, runner, cards, clock, store


async def _asked(run, runner, cards):
    await until(lambda: bool(cards) and "U3" in runner.started)
    await settle()
    assert not run.done(), "the run waits for the answer"
    return cards[0]


def _assert_held(result, runner, store):
    assert result.held == ["U1"] and "U2" in result.skipped and not result.failed
    assert runner.runs == ["U3"], "the held unit and its dependant never ran; the independent unit did"
    worker = next(e["target"] for e in events_of(store, "agent.assigned") if e["data"]["unit"] == "U1")
    mine = [e for e in store.read_events("org_demo", WORLD) if worker in (e["actor"], e["target"])]
    types = [e["type"] for e in mine]
    assert "agent.working" not in types and "agent.handoff" not in types and "artifact.created" not in types
    assert types[-1] == "agent.retired", "the held agent leaves without starting"
    assert len(events_of(store, "question.answered")) == 1


@pytest.mark.parametrize(
    ("actions", "replies", "hold", "proceed"),
    [
        (["send_email"], {}, "o1", "o2"),  # sensitive_step: "Hold this step" / "Prepare it"
        ([], {SEND_TITLE: ""}, "o1", "o2"),  # an unreadable reply: "Hold this step" / "Go ahead"
    ],
    ids=["sensitive_step", "unreadable_reply"],
)
def test_FR_HIL_10_a_rule_card_runs_the_unit_only_on_its_proceed_option(tmp_path, actions, replies, hold, proceed):
    async def held():
        run, wait, runner, cards, _clock, store = _setup(tmp_path / "a", actions=actions, replies=replies)
        card = await _asked(run, runner, cards)
        assert card["options"][0]["id"] == hold and card["safe_default"] == hold
        await asyncio.to_thread(wait.write, answered_part(card, option=hold))
        return await asyncio.wait_for(run, 20), runner, store

    result, runner, store = asyncio.run(held())
    _assert_held(result, runner, store)

    async def proceeds():
        run, wait, runner, cards, _clock, store = _setup(tmp_path / "b", actions=actions, replies=replies)
        card = await _asked(run, runner, cards)
        await asyncio.to_thread(wait.write, answered_part(card, option=proceed))
        return await asyncio.wait_for(run, 20), runner

    result, runner = asyncio.run(proceeds())
    assert runner.runs.count("U1") == 1 and runner.runs.index("U2") > runner.runs.index("U1")
    assert runner.answers["U1"].option == proceed and not result.held and not result.skipped


def test_FR_HIL_10_the_deadline_default_leaves_a_rule_card_s_unit_unrun(tmp_path) -> None:
    async def go():
        run, _wait, runner, cards, clock, store = _setup(tmp_path, actions=["send_email"])
        await _asked(run, runner, cards)
        await until(lambda: clock.pending_sleepers() >= 1)
        clock.advance(3600 + 5)
        return await asyncio.wait_for(run, 20), runner, store

    result, runner, store = asyncio.run(go())
    _assert_held(result, runner, store)
    (answered,) = events_of(store, "question.answered")
    assert (answered["data"]["answered_by"], answered["severity"]) == ("default", "nudge")


@pytest.mark.parametrize("option", ["o1", "o2"])
def test_FR_HIL_10_a_model_written_card_runs_on_a_persons_answer_whichever_option(tmp_path, option) -> None:
    async def go():
        run, wait, runner, cards, _clock, _store = _setup(
            tmp_path, actions=[], replies={SEND_TITLE: json.dumps(ASK_TASK["model_reply"])}
        )
        card = await _asked(run, runner, cards)
        await asyncio.to_thread(wait.write, answered_part(card, option=option))
        return await asyncio.wait_for(run, 20), runner

    result, runner = asyncio.run(go())
    assert runner.answers["U1"].option == option and not result.held and runner.runs.count("U1") == 1


def test_FR_HIL_10_a_model_written_card_s_default_at_the_deadline_runs_the_unit_with_it(tmp_path) -> None:
    async def go():
        run, _wait, runner, cards, clock, store = _setup(
            tmp_path, actions=[], replies={SEND_TITLE: json.dumps(ASK_TASK["model_reply"])}
        )
        card = await _asked(run, runner, cards)
        await until(lambda: clock.pending_sleepers() >= 1)
        clock.advance(3600 + 5)
        return await asyncio.wait_for(run, 20), runner, store, card

    result, runner, store, card = asyncio.run(go())
    answer = runner.answers["U1"]
    assert (answer.option, answer.answered_by) == (card["safe_default"], "default")
    assert runner.runs.count("U1") == 1 and not result.held and not result.skipped
    (answered,) = events_of(store, "question.answered")
    assert (answered["data"]["answered_by"], answered["severity"]) == ("default", "nudge")
