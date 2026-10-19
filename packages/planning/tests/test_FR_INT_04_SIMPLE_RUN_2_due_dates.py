"""SIMPLE-RUN-2 / FR-INT-04: a deadline said in words is read against the clock, in code, and what cannot be read is
refused in plain words; a skip never is."""

from __future__ import annotations

from datetime import date

import pytest
from tilo_planning.brief import BriefValidationError, edit_brief_field, vet_sources
from tilo_planning.due_dates import DEADLINE_HELP, parse_deadline
from tilo_planning.questions import Question, apply_answer, record_assumption

WED = date(2026, 10, 14)
BRIEF = {
    "goal": "Plan the supplier review.",
    "deliverables": [{"title": "Review", "format": "pdf"}],
    "audience": "Ops",
    "deadline": None,
    "constraints": [],
    "sources": [],
    "sensitivity": "business",
    "assumptions": [],
    "applied_preferences": [],
}


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("today", WED),
        ("By today", WED),
        ("Today, 2026-10-14", WED),
        ("by EOD", WED),
        ("tomorrow", date(2026, 10, 15)),
        ("day after tomorrow", date(2026, 10, 16)),
        ("by the end of this week", date(2026, 10, 16)),
        ("end of next week", date(2026, 10, 23)),
        ("Friday", date(2026, 10, 16)),
        ("on Wednesday", WED),
        ("next Wednesday", date(2026, 10, 21)),
        ("next monday", date(2026, 10, 19)),
        ("in 3 days", date(2026, 10, 17)),
        ("in two weeks", date(2026, 10, 28)),
        ("20 Oct", date(2026, 10, 20)),
        ("October 20th", date(2026, 10, 20)),
        ("5 Oct", date(2027, 10, 5)),
        ("12 Mar 2027", date(2027, 3, 12)),
        ("end of the month", date(2026, 10, 31)),
        ("2026-11-02", date(2026, 11, 2)),
    ],
)
def test_FR_INT_04_SIMPLE_RUN_2_deadline_words_read_against_the_clock(said, expected):
    assert parse_deadline(said, WED) == (True, expected)


@pytest.mark.parametrize("said", ["No firm deadline", "none", "whenever"])
def test_FR_INT_04_SIMPLE_RUN_2_no_deadline_words_clear_it(said):
    assert parse_deadline(said, WED) == (True, None)


@pytest.mark.parametrize("said", ["", "banana", "31 feb", "when the stars align", "2026-13-45"])
def test_FR_INT_04_SIMPLE_RUN_2_unreadable_words_are_not_guessed(said):
    assert parse_deadline(said, WED) == (False, None)


def test_FR_INT_04_SIMPLE_RUN_2_a_deadline_answer_and_edit_in_words_set_the_date_or_say_what_is_wanted():
    question = Question("deadline", "When is this due?", ("No firm deadline", "By the end of this week"), 0.4)
    assert apply_answer(BRIEF, question, "by today", today=WED)["deadline"] == "2026-10-14"
    assert edit_brief_field(BRIEF, "deadline", "tomorrow", today=WED)["deadline"] == "2026-10-15"
    with pytest.raises(BriefValidationError, match=DEADLINE_HELP[:20]):
        apply_answer(BRIEF, question, "banana", today=WED)
    with pytest.raises(BriefValidationError):
        edit_brief_field(BRIEF, "deadline", "banana", today=WED)


def test_FR_INT_04_SIMPLE_RUN_2_skipping_a_date_question_records_the_guess_and_never_raises():
    question = Question("deadline", "When is this due?", ("No firm deadline", "By the end of this week"), 0.4)
    brief = record_assumption(BRIEF, question, today=WED)
    assert brief["deadline"] is None
    assert brief["assumptions"][-1]["assumed"] == "Deadline: No firm deadline"


def test_FR_INT_03_SIMPLE_RUN_2_vet_sources_keeps_only_what_code_can_stand_behind():
    kept = vet_sources(
        [
            {"kind": "memory", "ref": "Demo"},
            {"kind": "file", "ref": "x"},
            {"kind": "url", "ref": "ftp://x"},
            {"kind": "url", "ref": "https://example.com/a"},
            {"kind": "connector", "ref": "nope"},
            {"kind": "connector", "ref": "gmail"},
            {"kind": "web", "ref": "prices"},
        ]
    )
    assert [(s["kind"], s["ref"]) for s in kept] == [
        ("url", "https://example.com/a"),
        ("connector", "gmail"),
        ("web", "prices"),
    ]
