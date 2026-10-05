"""FR-AGT-05 (PRD 8.3): "An agent must ask its supervisor, and the supervisor must ask a person."
"Each question carries context, options, a suggested answer, a deadline and a safe default."

Given a unit whose model reply plants an ambiguity, When the harness raises the question, Then the
Trace shows the chain Specialist -> Lead (agent.help_requested), Lead -> Director (agent.escalated
with the must-ask reason) and Lead -> a person (question.routed), every event is a registered,
valid TiloEvent, and the card that question.routed points at is a valid needs_you card with 2 or 3
options, exactly one suggested (with its reason), a positive timeout and a reversible safe default.
"""

from __future__ import annotations

import asyncio

import pytest
from agt_must_ask_support import (
    DIRECTOR,
    LEAD,
    OWNER,
    SPECIALIST,
    WORLD,
    card_problems,
    layout_for_asks,
    make_must_ask,
    raise_for,
    specialist_script,
    tasks_of,
    unit_for,
)
from conftest import ULID_PATTERN, make_memory_writer
from tilo_harness.validator import EventValidator


def _raise(tmp_path, task):
    specialist = specialist_script([task])
    must_ask, cards, _providers = make_must_ask(tmp_path, specialist)
    writer, store = make_memory_writer(layout_for_asks(), world_id=WORLD)
    unit = unit_for(task)
    ask = asyncio.run(must_ask.assess(unit))
    assert ask is not None, f"{task['id']} plants a question"
    card = raise_for(must_ask, ask, writer, unit)
    assert specialist.misses == []
    return card, cards, store.read_events("org_demo", WORLD), ask


@pytest.mark.parametrize("task", tasks_of("ask"), ids=lambda task: task["id"])
def test_FR_AGT_05_the_question_climbs_specialist_lead_director_then_a_person(tmp_path, task) -> None:
    _card, _cards, events, ask = _raise(tmp_path, task)

    assert [event["type"] for event in events] == ["agent.help_requested", "agent.escalated", "question.routed"]
    helped, escalated, routed = events

    assert (helped["actor"], helped["target"]) == (SPECIALIST, LEAD), "the agent asks its supervisor first"
    assert helped["data"]["unit"] == "U1"
    assert (escalated["actor"], escalated["target"]) == (LEAD, DIRECTOR)
    assert escalated["data"]["reason"] == ask.reason == task["model_reply"]["reason"]
    assert routed["actor"] == LEAD, "the supervisor asks the person"
    assert routed["target"] == OWNER and routed["target"].startswith("u_"), "a person, not an agent"
    assert routed["severity"] == "needs_you"
    assert routed["data"]["domain"] is None, "no Team Lead is configured: the owner fallback (FR-AGT-06)"
    assert [event["seq"] for event in events] == sorted(event["seq"] for event in events)


def test_FR_AGT_05_every_question_event_is_registered_valid_and_densely_sequenced(tmp_path, repo_root) -> None:
    _card, _cards, events, _ask = _raise(tmp_path, tasks_of("ask")[0])
    validator = EventValidator.from_repo(repo_root)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert {i: validator.problems(e) for i, e in enumerate(events) if validator.problems(e)} == {}


@pytest.mark.parametrize("task", tasks_of("ask"), ids=lambda task: task["id"])
def test_FR_AGT_05_the_card_carries_context_options_suggestion_deadline_and_safe_default(tmp_path, task) -> None:
    card, cards, events, _ask = _raise(tmp_path, task)
    reply = task["model_reply"]
    routed = events[-1]

    assert cards == [card], "the card goes to the card sink exactly once"
    assert card_problems(card) == [], "contracts/card.schema.json plus CR-01 and CR-02"
    assert ULID_PATTERN.match(card["id"]) and card["id"] == routed["data"]["card_id"]
    assert (card["kind"], card["rung"]) == ("needs_you", "needs_you")
    assert card["world_id"] == WORLD

    assert card["what_happened"].strip() and card["why_it_matters"].strip(), "context"
    assert reply["question"] in (card["what_happened"], card["why_it_matters"]), "the question itself is on the card"

    assert [option["label"] for option in card["options"]] == reply["options"], "options, in the model's order"
    suggested = [option for option in card["options"] if option["suggested"]]
    assert len(suggested) == 1, "exactly one suggested answer"
    assert suggested[0]["label"] == reply["options"][reply["suggested"]]
    assert suggested[0]["reason"] == reply["why"]

    assert isinstance(card["timeout"], int) and card["timeout"] > 0, "a deadline"
    safe = next(option for option in card["options"] if option["id"] == card["safe_default"])
    assert safe["irreversible"] is False, "a safe default is always reversible (CR-03)"
    assert card["gate"] is None and card["consent"] is None


def test_FR_AGT_05_a_repeated_failure_question_is_also_a_valid_card_with_the_failure_reason(tmp_path) -> None:
    """The deterministic rules produce a full question too, with no model reply to copy from."""
    from agt_scripted import ScriptedProvider

    must_ask, cards, _providers = make_must_ask(tmp_path, ScriptedProvider(default='{"ask": false}'))
    writer, store = make_memory_writer(layout_for_asks(), world_id=WORLD)
    unit = unit_for({"title": "Reconcile the ledger export", "actions": []})

    ask = asyncio.run(must_ask.assess(unit, failures=3))
    assert ask is not None and ask.reason == "repeated_failure"
    card = raise_for(must_ask, ask, writer, unit)

    events = store.read_events("org_demo", WORLD)
    assert [event["type"] for event in events] == ["agent.help_requested", "agent.escalated", "question.routed"]
    assert events[1]["data"]["reason"] == "repeated_failure"
    assert card_problems(card) == [] and cards == [card]
    assert 2 <= len(card["options"]) <= 3 and any(option["suggested"] for option in card["options"])


def test_FR_AGT_05_a_question_never_carries_a_secret_or_model_id(tmp_path) -> None:
    """PL-01 and the secrets rule: nothing a model id or key-looking string may leak into the card."""
    import json
    import re

    card, _cards, events, _ask = _raise(tmp_path, tasks_of("ask")[0])
    text = json.dumps([card, events])
    assert not re.search(r"gemini|flash-3|lite-31|gpt-|claude-|sk-[A-Za-z0-9]{8}|AIza", text)
