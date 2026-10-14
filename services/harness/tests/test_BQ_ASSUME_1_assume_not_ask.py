"""BQ-ASSUME-1 (owner decision, SIMPLE-RUN: "too many questions lead to a weak product"): a question the model raises
mid-run about an ambiguity or a trade-off no longer stops the run. The unit goes on with the model's suggested option
and one visible "Assumed: ..." event records it. Every deterministic ask stays: repeated failure, an action above T1,
T3, and a model-raised sensitive_step. `config/must_ask.yaml` (`model_questions: assume | ask`) is the switch.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agt_must_ask_support import DIRECTOR, LEAD, WORLD, make_must_ask, unit_for
from agt_scripted import ScriptedProvider
from agt_support import (
    RecordingRunner,
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from tilo_harness.executor import run_plan
from tilo_harness.must_ask import Assumption, load_model_questions

TITLE = "Research the market for standing desks"
REGION_ASK = {
    "ask": True,
    "reason": "ambiguous_brief",
    "question": "Which geographic region or country should I focus the research on?",
    "options": ["Europe", "North America", "Global"],
    "suggested": 0,
    "why": "Most buyers are there.",
}
TRADE_OFF = {**REGION_ASK, "reason": "trade_off", "question": "Skip the second source check to save time?"}
SENSITIVE = {**REGION_ASK, "reason": "sensitive_step", "question": "Share the draft with the supplier?"}
BRIEF = {
    "goal": "Compare standing desk suppliers for our team",
    "audience": "The operations lead",
    "constraints": ["Under 500 dollars each"],
    "assumptions": [{"question": "Which budget?", "assumed": "Budget: 500 dollars per desk"}],
}


def _unit(actions=()):
    return unit_for({"title": TITLE, "actions": list(actions)})


def _assess(tmp_path, reply, unit=None, *, failures=0, mode="assume", brief=None, covered=()):
    specialist = ScriptedProvider(default=reply if isinstance(reply, str) else json.dumps(reply))
    must_ask, cards, _ = make_must_ask(tmp_path, specialist, model_questions=mode, brief=brief, covered_actions=covered)
    result = asyncio.run(must_ask.assess(unit or _unit(), failures=failures))
    return result, cards, specialist


@pytest.mark.parametrize("reply, reason", [(REGION_ASK, "ambiguous_brief"), (TRADE_OFF, "trade_off")])
def test_BQ_ASSUME_1_a_model_ambiguity_or_trade_off_is_assumed_not_asked(tmp_path, reply, reason) -> None:
    result, cards, _ = _assess(tmp_path, reply)

    assert isinstance(result, Assumption), result
    assert result.reason == reason
    assert result.line.startswith("Assumed: ") and len(result.line) <= 140
    assert reply["options"][0] in result.line  # the model's suggested option
    assert cards == []


def test_BQ_ASSUME_1_the_ask_mode_keeps_the_card(tmp_path) -> None:
    result, _cards, _ = _assess(tmp_path, REGION_ASK, mode="ask")

    assert result is not None and not isinstance(result, Assumption)
    assert result.reason == "ambiguous_brief"


@pytest.mark.parametrize("reply", ["not json", json.dumps({"ask": "maybe"}), ""])
def test_BQ_ASSUME_1_an_unreadable_reply_proceeds_as_no_question_needed(tmp_path, reply) -> None:
    result, cards, _ = _assess(tmp_path, reply)

    assert isinstance(result, Assumption) and result.line == "Assumed: no question needed"
    assert cards == []
    asked, _, _ = _assess(tmp_path, reply, mode="ask")
    assert asked is not None and asked.reason == "ambiguous_brief"  # ask mode: the old Hold / Go ahead card


@pytest.mark.parametrize("action", ["send_email", "post_status_update", "wire_money", "delete_file"])
def test_BQ_ASSUME_1_an_action_above_t1_still_asks(tmp_path, action) -> None:
    result, _, specialist = _assess(tmp_path, {"ask": False}, _unit([action]))

    assert result is not None and result.reason == "sensitive_step"
    assert specialist.call_count == 0  # decided by rule, never by the model


def test_BQ_ASSUME_1_t3_is_never_waved_through_by_coverage(tmp_path) -> None:
    result, _, _ = _assess(tmp_path, {"ask": False}, _unit(["wire_money"]), covered={"wire_money"})

    assert result is not None and result.reason == "sensitive_step"


def test_BQ_ASSUME_1_repeated_failure_still_asks(tmp_path) -> None:
    result, _, specialist = _assess(tmp_path, REGION_ASK, failures=3)

    assert result is not None and result.reason == "repeated_failure"
    assert specialist.call_count == 0


def test_BQ_ASSUME_1_a_model_raised_sensitive_step_still_asks(tmp_path) -> None:
    result, _, _ = _assess(tmp_path, SENSITIVE)

    assert result is not None and not isinstance(result, Assumption)
    assert result.reason == "sensitive_step"


def test_BQ_ASSUME_1_the_model_is_given_the_goal_and_what_is_already_decided(tmp_path) -> None:
    _, _, specialist = _assess(tmp_path, {"ask": False}, brief=BRIEF)

    prompt = specialist.prompts[-1]
    assert "Compare standing desk suppliers for our team" in prompt
    assert "Budget: 500 dollars per desk" in prompt and "The operations lead" in prompt


def test_BQ_ASSUME_1_the_switch_is_configuration(tmp_path) -> None:
    shipped = Path(__file__).resolve().parents[3] / "config" / "must_ask.yaml"
    assert load_model_questions(shipped) == "assume"  # the owner's default

    def write(text: str) -> Path:
        path = tmp_path / "must_ask.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    assert load_model_questions(tmp_path / "missing.yaml") == "assume"
    assert load_model_questions(write("model_questions: ask\n")) == "ask"
    assert load_model_questions(write("model_questions: sometimes\n")) == "ask"  # a typo never removes a question
    assert load_model_questions(write("{ not yaml")) == "ask"


class _ContextRunner(RecordingRunner):
    def __init__(self) -> None:
        super().__init__(release_immediately=True)
        self.contexts: dict[str, object] = {}

    async def run(self, unit, context):
        self.contexts[unit["id"]] = context
        return await super().run(unit, context)


def test_BQ_ASSUME_1_run_plan_goes_on_and_records_one_visible_assumption(tmp_path) -> None:
    layout = build_layout(
        world_id=WORLD,
        director_id=DIRECTOR,
        district_specs=[{"id": "D1", "lead": LEAD, "specialists": ["A_s0"], "unit_ids": ["U1"]}],
    )
    plan = build_plan([build_unit("U1", title=TITLE)])
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    skills = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id=WORLD)
    runner = _ContextRunner()
    must_ask, cards, _ = make_must_ask(
        tmp_path, ScriptedProvider(default=json.dumps(REGION_ASK)), model_questions="assume", brief=BRIEF
    )

    asyncio.run(
        asyncio.wait_for(
            run_plan(plan, layout, writer=writer, config=config, skills=skills, runner=runner, must_ask=must_ask),
            timeout=20,
        )
    )

    events = store.read_events("org_demo", WORLD)
    assert runner.starts == ["U1"] and cards == []  # the unit ran; nobody was asked
    assert not [e for e in events if e["type"] in {"agent.help_requested", "agent.escalated", "question.routed"}]
    assumed = [e for e in events if e["type"] == "agent.working" and e["summary"].startswith("Assumed: ")]
    assert len(assumed) == 1 and "Europe" in assumed[0]["summary"]
    told = runner.contexts["U1"].intake_answers  # the unit is told the question and the assumed answer
    assert told and told[-1][1] == "Europe"
