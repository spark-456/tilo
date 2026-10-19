"""FR-PA-08 guards (API_FR_PA_08.md sections 6 and 7): behaviour that is true today and must stay true when the STATUS
and weekly intents land. This file is never pending: it passes now and a builder who breaks one of these has broken
the panel, not the new feature. (Nothing here is the new behaviour; see `test_FR_PA_08_s1_status.py` and
`test_FR_PA_08_s2_weekly.py`.)
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from _fr_pa_08_lib import STATUS_QUESTIONS, WEEKLY_QUESTIONS
from _ppl11b_lib import (
    DECLINES,
    REPO_ROOT,
    SAM,
    AccessSpy,
    ScriptedDecider,
    mod,
    plate_s1,
    principal,
    run_answer,
    unwire_plate_sources,
)
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from _ppl11b_lib import world as world  # noqa: PLC0414  (the fixture)

OLDER_INTENTS = [
    ("What is the status of my tasks?", "tasks"),
    ("How are my tasks going?", "tasks"),
    ("What changed since yesterday?", "changed"),
    ("What's new?", "changed"),
    ("What is due this week?", "due_soon"),
    ("What is on my calendar this week?", "calendar_today"),
    ("What is on my plate?", "plate"),
    ("What is overdue?", "overdue"),
]


@pytest.mark.parametrize(("question", "intent"), OLDER_INTENTS)
def test_FR_PA_08_guard_the_older_fact_questions_keep_their_intents(world, question, intent):
    """The STATUS and weekly words must not take over FR-PA-13's pinned questions (PPL-11b A13-1)."""
    answer = run_answer(world, plate_s1(), question, decider=ScriptedDecider())
    assert (answer.outcome, answer.decided_by, answer.intent) == ("answered", "rules", intent), question


@pytest.mark.parametrize(
    "question",
    [
        "What is Priya's status?",
        "Give me her status update",
        "What is his status?",
        "Priya's weekly summary",
        "Weekly summary for my manager",
        "How was her week?",
        "Status of my teammates",
        "Give me everyone's status update",
    ],
)
def test_FR_PA_08_guard_status_and_weekly_about_someone_else_are_declined_before_anything_is_read(
    world, monkeypatch, question
):
    spy = AccessSpy(monkeypatch)
    decider = ScriptedDecider()
    answer = run_answer(world, plate_s1(), question, decider=decider)
    assert (answer.outcome, answer.decided_by, answer.decline) == ("declined", "rules", "other_person"), question
    assert answer.lines[0].text == DECLINES["other_person"] and answer.lines[0].source is None
    assert decider.calls == 0 and spy.all_requests() == [], (
        "nothing is looked up: the reply cannot depend on anyone else"
    )


@pytest.mark.parametrize("question", [STATUS_QUESTIONS[0], WEEKLY_QUESTIONS[0]])
def test_FR_PA_08_guard_a_failing_plate_source_is_a_failed_answer_never_a_partial_one(rig_factory, question):
    rig = rig_factory()

    class Down:
        def build(self, user, now):
            raise RuntimeError("plate source down (test double)")

    rig.plate_source = Down()
    rig.activate()
    response = rig.ask(question)
    body = response.json()
    assert response.status_code == 200
    assert (body["outcome"], body["decided_by"], body["sources"], body["text"]) == (
        "failed",
        "rules",
        [],
        DECLINES["failed"],
    )
    assert "RuntimeError" in rig.logs() and "plate source down" not in rig.logs()


@pytest.mark.parametrize("question", [STATUS_QUESTIONS[0], WEEKLY_QUESTIONS[0]])
def test_FR_PA_08_guard_an_email_principal_is_refused_and_an_unwired_seam_is_503(rig_factory, question, monkeypatch):
    rig = rig_factory(who=principal(SAM, channel="email"))
    refused = rig.ask(question)
    assert refused.status_code == 403 and refused.json() == {"error": "channel"} and rig.nothing_stored()
    rig.set_principal(principal(SAM))
    rig.unwire("get_plate_source")
    unwire_plate_sources(monkeypatch)  # the sources under it now read the store (PEOPLE-SEAMS-1): unwired on purpose
    unwired = rig.ask(question)
    assert unwired.status_code == 503 and unwired.json() == {"detail": "not_configured"} and rig.nothing_stored()


def test_FR_PA_08_guard_nothing_in_the_assistant_package_reads_a_clock_except_the_route_once():
    """The window is a function of the request clock, never of the wall clock (spec section 2)."""
    root = pathlib.Path(mod("tilo_api.assistant").__file__).parent
    reads: dict[str, int] = {}
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}:
                    reads[path.name] = reads.get(path.name, 0) + 1
    assert reads in ({"route.py": 1}, {}), f"clock reads outside the route: {reads}"


def test_FR_PA_08_guard_the_assistant_config_names_no_person_record_world_or_model():
    """The STATUS and weekly words are fixed lists over the person's own question: no person, record or model id in
    config/assistant.yaml (FR-PA-17, PL-01); the new intents join `facts`, they add no key that names one."""
    text = (REPO_ROOT / "config" / "assistant.yaml").read_text(encoding="utf-8")
    assert not re.search(r"\b(u_|wi_|pb_|ce_|mt_|w_)[a-z0-9]", text), "no record id in the rules"
    assert not re.search(r"(?i)gemini|claude|gpt|nemotron|llama", text), "no model id outside config/models*.yaml"
