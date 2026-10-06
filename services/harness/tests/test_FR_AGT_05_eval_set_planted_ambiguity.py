"""FR-AGT-05 (PRD 8.3, 8.6): "Eval tasks with planted ambiguity raise a question; clear tasks raise
none."

Given the scripted eval set (fixtures/must_ask/tasks.json: 12 tasks that plant an ambiguity, a
trade-off or a sensitive step, and 12 clear tasks, each with the recorded reply of the
specialist-role model), When each task's unit is assessed and, if a question is due, raised through
the harness, Then every planted task raises exactly one question of the planted kind and every clear
task raises none: no help request, no escalation, no routed question, no card.

The model call goes through the provider layer by role (PL-01) and is scripted, so nothing here
touches a network or costs a credit (EFF-01). The interface is pinned in agt_must_ask_support.py.
"""

from __future__ import annotations

import asyncio

from agt_must_ask_support import (
    OWNER,
    WORLD,
    layout_for_asks,
    load_tasks,
    make_must_ask,
    raise_for,
    specialist_script,
    tasks_of,
    unit_for,
)
from conftest import make_memory_writer

QUESTION_EVENT_TYPES = {"agent.help_requested", "agent.escalated", "question.routed"}


def _run_eval(tmp_path):
    tasks = load_tasks()
    specialist = specialist_script(tasks)
    must_ask, cards, _providers = make_must_ask(tmp_path, specialist)
    writer, store = make_memory_writer(layout_for_asks(), world_id=WORLD)
    outcomes: dict[str, tuple[object, list[dict]]] = {}
    for task in tasks:
        before = len(store.read_events("org_demo", WORLD))
        unit = unit_for(task)
        ask = asyncio.run(must_ask.assess(unit))
        if ask is not None:
            raise_for(must_ask, ask, writer, unit)
        written = store.read_events("org_demo", WORLD)[before:]
        outcomes[task["id"]] = (ask, written)
    return outcomes, specialist, cards


def test_FR_AGT_05_eval_set_has_the_planted_and_clear_tasks_the_acceptance_test_needs() -> None:
    assert len(tasks_of("ask")) == 12
    assert len(tasks_of("clear")) == 12
    assert {task["model_reply"].get("reason") for task in tasks_of("ask")} == {
        "ambiguous_brief",
        "trade_off",
        "sensitive_step",
    }


def test_FR_AGT_05_every_planted_ambiguity_raises_exactly_one_question_of_the_planted_kind(tmp_path) -> None:
    outcomes, specialist, cards = _run_eval(tmp_path)
    assert specialist.misses == [], f"the harness sent a prompt the recording does not know: {specialist.misses}"

    for task in tasks_of("ask"):
        ask, written = outcomes[task["id"]]
        assert ask is not None, f"FR-AGT-05: {task['id']} plants {task['model_reply']['reason']} but raised no question"
        assert ask.reason == task["model_reply"]["reason"], task["id"]
        types = [event["type"] for event in written]
        assert sorted(types) == sorted(QUESTION_EVENT_TYPES), f"{task['id']}: expected one chain, got {types}"
        routed = [event for event in written if event["type"] == "question.routed"]
        assert len(routed) == 1
        assert routed[0]["target"] == OWNER, "no Team Lead is configured, so the owner is asked (FR-AGT-06 fallback)"

    assert len(cards) == len(tasks_of("ask")), "one card per planted question"


def test_FR_AGT_05_clear_tasks_raise_no_question_event_and_no_card(tmp_path) -> None:
    outcomes, specialist, cards = _run_eval(tmp_path)
    assert specialist.misses == []

    for task in tasks_of("clear"):
        ask, written = outcomes[task["id"]]
        assert ask is None, f"FR-AGT-05: clear task {task['id']} raised a {ask.reason} question"
        assert written == [], f"FR-AGT-05: clear task {task['id']} wrote events {[e['type'] for e in written]}"

    assert len(cards) == len(tasks_of("ask")), "a clear task must never put a card in the needs-you queue"


def test_FR_AGT_05_the_assessment_reaches_a_model_only_through_the_specialist_role_provider(tmp_path) -> None:
    tasks = tasks_of("clear")[:3]
    specialist = specialist_script(tasks)
    must_ask, _cards, providers = make_must_ask(tmp_path, specialist)

    for task in tasks:
        assert asyncio.run(must_ask.assess(unit_for(task))) is None

    assert specialist.call_count >= len(tasks), "a clear task is judged by the model of the unit's role"
    for role in ("director", "lead", "verifier", "writer", "narrator"):
        assert providers[role].call_count == 0, f"PL-01: the {role} provider must not answer a specialist's question"
