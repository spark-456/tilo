"""SIMPLE-RUN-2 / FR-INT-03, FR-INT-04, FR-INT-08: nothing between intake and run start refuses a person for a reason
they cannot see. A date asked twice is asked once; a date answered in words ("by today") is read against the clock;
a skip never 422s; a Director-invented source never reaches a live brief; and a run that cannot start is a plain
503 before anything is approved, retried by Start again (LIVE-PATH-AUDIT-A finding 6)."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

import pytest
from _clint1_lib import Flow, brief_reply, make_spy_safety

TODAY = date(2026, 10, 14)
DATE_QUESTION = {
    "label": "Meeting date",
    "text": "What date should this meeting be scheduled for?",
    "suggested_answers": ["Today"],
    "expected_change": 0.9,
}


@pytest.fixture()
def build(repo_root, store):
    from tilo_api import deps

    made: list[Flow] = []

    def make(reply: dict[str, Any]) -> Flow:
        flow = Flow(repo_root, store, make_spy_safety(), reply)
        flow.app.dependency_overrides[deps.get_today] = lambda: lambda: TODAY  # a Clock
        made.append(flow)
        return flow

    yield make
    for flow in made:
        flow.app.dependency_overrides.clear()


def _reply(ambiguous: list[str], **extra: Any) -> dict[str, Any]:
    return {**copy.deepcopy(brief_reply(ambiguous)), **extra}


def test_FR_INT_04_SIMPLE_RUN_2_every_question_has_its_own_field(build):
    flow = build(_reply(["deadline", "audience"], questions=[DATE_QUESTION, {**DATE_QUESTION, "label": "Other"}]))

    intake = flow.new_task()

    fields = [q["field"] for q in intake["questions"]]
    assert len(fields) == len(set(fields))
    assert 1 <= len(fields) <= 3


def test_FR_INT_04_SIMPLE_RUN_2_skipping_every_question_never_refuses_and_approaches_follow(build):
    flow = build(_reply(["deadline", "audience", "constraints"], questions=[DATE_QUESTION]))
    intake = flow.new_task()

    skipped = flow.answers(intake["task_id"], [{"field": q["field"], "answer": None} for q in intake["questions"]])

    assert skipped.status_code == 200, skipped.text
    assert flow.approaches(intake["task_id"]).status_code == 200


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("By today", "2026-10-14"),
        ("Today, 2026-10-14", "2026-10-14"),
        ("tomorrow", "2026-10-15"),
        ("Friday", "2026-10-16"),
    ],
)
def test_FR_INT_04_SIMPLE_RUN_2_a_date_typed_in_words_is_read_against_the_clock(build, typed, expected):
    flow = build(_reply(["deadline"]))
    intake = flow.new_task()
    assert [q["field"] for q in intake["questions"]] == ["deadline"]

    response = flow.answers(intake["task_id"], [{"field": "deadline", "answer": typed}])

    assert response.status_code == 200, response.text
    assert response.json()["brief"]["deadline"] == expected


def test_FR_INT_04_SIMPLE_RUN_2_a_deadline_chip_edit_in_words_is_read_and_unreadable_words_say_so(build):
    flow = build(_reply(["audience"]))
    intake = flow.new_task()
    answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]

    edited = flow.answers(intake["task_id"], answers, brief_edits={"deadline": "by the end of this week"})
    assert edited.status_code == 200, edited.text
    assert edited.json()["brief"]["deadline"] == "2026-10-16"

    refused = flow.answers(intake["task_id"], answers, brief_edits={"deadline": "when the stars align"})
    assert refused.status_code == 422
    assert "date" in refused.json()["detail"].lower() and "skip" in refused.json()["detail"].lower()


def test_FR_INT_03_SIMPLE_RUN_2_a_source_the_director_invented_never_reaches_the_brief(build):
    invented = [
        {"kind": "memory", "ref": "Demo", "label": "Demo"},
        {"kind": "file", "ref": "art_made_up"},
        {"kind": "url", "ref": "not a url"},
        {"kind": "connector", "ref": "no_such_connector"},
        {"kind": "url", "ref": "https://example.com/prices"},
        {"kind": "web", "ref": "weekly supplier prices"},
        {"kind": "connector", "ref": "gmail"},
    ]
    flow = build(_reply([], sources=invented))

    brief = flow.new_task()["brief"]

    assert [(s["kind"], s["ref"]) for s in brief["sources"]] == [
        ("url", "https://example.com/prices"),
        ("web", "weekly supplier prices"),
        ("connector", "gmail"),
    ]


def _approvable(flow: Flow) -> dict[str, Any]:
    intake = flow.task_with_approaches()
    return intake


def test_FR_INT_08_SIMPLE_RUN_2_a_run_that_cannot_start_is_a_plain_503_before_anything_is_approved(build, monkeypatch):
    from tilo_api import runs, tasks

    flow = build(_reply([]))
    intake = _approvable(flow)
    monkeypatch.setattr(tasks, "_loud", lambda: True)
    flow.app.dependency_overrides[runs.run_seams] = lambda: None

    refused = flow.approve(intake["task_id"], "quick", 80)

    assert refused.status_code == 503, refused.text
    detail = refused.json()["detail"]
    assert "nothing was charged" in detail and "Start again" in detail
    assert flow.events(intake["world_id"], "budget.granted") == []  # nothing approved
    assert not flow.store.tasks[intake["task_id"]].granted


def test_FR_INT_08_SIMPLE_RUN_2_start_again_starts_a_granted_run_that_never_started(build, monkeypatch):
    from tilo_api import runs, tasks

    flow = build(_reply([]))
    intake = _approvable(flow)
    seams = object()
    started: list[float] = []

    def failing_start(store, task, *, approach, budget_cap, seams):
        raise RuntimeError("thread could not start")

    flow.app.dependency_overrides[runs.run_seams] = lambda: seams
    monkeypatch.setattr(tasks, "_loud", lambda: True)
    monkeypatch.setattr(runs, "start_run", failing_start)
    first = flow.approve(intake["task_id"], "quick", 80)
    assert first.status_code == 503, first.text
    assert flow.store.tasks[intake["task_id"]].granted, "the grant stays recorded"

    monkeypatch.setattr(
        runs, "start_run", lambda store, task, *, approach, budget_cap, seams: started.append(budget_cap)
    )
    again = flow.approve(intake["task_id"], "quick", 999)

    assert again.status_code == 200, again.text
    assert again.json() == {"world_id": intake["world_id"]}
    assert started == [80.0], "the recorded cap is kept; the second request's number never raises it"
    assert len(flow.events(intake["world_id"], "budget.granted")) == 1


def test_FR_INT_06_SIMPLE_RUN_2_approaches_say_the_most_one_approval_may_grant(build):
    flow = build(_reply([]))
    intake = flow.new_task()

    body = flow.approaches(intake["task_id"]).json()

    assert body["budget_ceiling"] == 300.0  # config/metering.yaml caps.run_credits
    too_much = flow.approve(intake["task_id"], body["recommended"], body["budget_ceiling"] + 1)
    assert too_much.status_code == 422
    assert "at most 300" in too_much.json()["detail"]
