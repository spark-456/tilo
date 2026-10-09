"""FR-INT-03 / FR-INT-04, INTAKE-QUALITY-1 slice 2: the Director's brief output gains `questions`, up to 3 questions
specific to the task (each with a label, text, up to 3 suggested answers whose first is the Director's guess, and an
expected_change). When the Director gives any, they replace the two generic "format?" and "rules?" questions; those
stay the fallback when it gives none. Answers are recorded into the brief as `Label: value` constraints (no contract
change). The model's question text and suggested answers are untrusted: clipped, stripped of markup and control
characters, capped. Scripted provider, no network."""

from __future__ import annotations

import json
from datetime import date

import pytest
from _planning_contracts_lib import (
    ScriptedCall,
    ScriptedModelProvider,
    assert_valid_brief,
    assert_valid_event,
    build_test_router,
    load_brief_fixture,
    make_no_memory,
    sample_event_base,
)
from tilo_planning.brief import BriefValidationError, complete_brief, extract_brief, output_schema
from tilo_planning.memory import InMemoryPreferenceStore
from tilo_planning.questions import MAX_QUESTIONS, apply_answer, generate_questions, record_assumption

TODAY = date(2026, 10, 9)
TOPIC = [
    {
        "label": "Branch",
        "text": "Which branch is the exam for?",
        "suggested_answers": ["CS", "EC", "ME"],
        "expected_change": 0.9,
    },
    {
        "label": "Level",
        "text": "How far along are you?",
        "suggested_answers": ["beginner", "some revision"],
        "expected_change": 0.8,
    },
    {
        "label": "Hours per day",
        "text": "How many hours a day?",
        "suggested_answers": ["3", "5"],
        "expected_change": 0.6,
    },
    {
        "label": "Practice",
        "text": "Do you want practice material?",
        "suggested_answers": ["yes", "no"],
        "expected_change": 0.4,
    },
]


def _reply(questions: object, **extra: object) -> str:
    return json.dumps({**load_brief_fixture("valid_market_scan"), "questions": questions, **extra})


def _extract(tmp_path, questions: object, **extra: object):
    provider = ScriptedModelProvider("large", [ScriptedCall(text=_reply(questions, **extra))])
    return extract_brief("Prepare for the exam.", router=build_test_router(tmp_path, provider))


def _brief() -> dict:
    return complete_brief(load_brief_fixture("valid_market_scan"))


def _topic_questions(tmp_path, ambiguous=(), questions=TOPIC, brief=None, memory=None):
    extraction = _extract(tmp_path, questions)
    return generate_questions(
        brief or extraction.brief,
        ambiguous,
        memory=memory or make_no_memory(),
        base=sample_event_base(),
        seq=2,
        topic_questions=extraction.questions,
    )


# --- the Director's output ------------------------------------------------------------------------------------


def test_FR_INT_03_the_director_output_schema_allows_questions_and_the_brief_never_keeps_them(tmp_path) -> None:
    assert "questions" in output_schema()["properties"] and "questions" not in output_schema()["required"]

    extraction = _extract(tmp_path, TOPIC)

    assert "questions" not in extraction.brief  # the contract's brief has no such key
    assert [q.label for q in extraction.questions] == ["Branch", "Level", "Hours per day"]  # top 3 by expected_change


def test_FR_INT_04_the_director_questions_are_ranked_capped_and_cleaned(tmp_path) -> None:
    messy = [
        {
            "label": "  Hours\tper\nday ",
            "text": "  <b>How many</b> hours?  \x00 ",
            "suggested_answers": ["3", "3", "4", "5", "6"],
            "expected_change": 0.3,
        },
        {
            "label": "Branch",
            "text": "Which branch? " + "x" * 500,
            "suggested_answers": ["CS " + "y" * 500],
            "expected_change": 5,
        },
        {"label": "Level", "text": "How far along?", "suggested_answers": ["beginner"], "expected_change": "high"},
    ]

    questions = _extract(tmp_path, messy).questions

    assert [q.label for q in questions] == ["Branch", "Level", "Hours per day"]
    branch, level, hours = questions
    assert branch.expected_change == 1.0 and level.expected_change == 0.5  # clamped to 0..1; unusable -> 0.5
    assert hours.text == "How many hours?", "tags, control characters and runs of spaces are removed"
    assert "<" not in hours.text and ">" not in hours.text and "\x00" not in hours.text
    assert hours.suggested_answers == ("3", "4", "5"), "duplicates dropped, at most 3 answers, the first is the guess"
    assert len(branch.text) <= 200 and all(len(a) <= 120 for q in questions for a in q.suggested_answers)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "a string",
        {"label": "Branch"},
        [None, 5, "x", []],
        [{"label": "", "text": "Which?", "suggested_answers": ["a"]}],
        [{"label": "Branch", "text": "", "suggested_answers": ["a"]}],
        [{"label": "Branch", "text": "Which?", "suggested_answers": []}],
        [{"label": "Branch", "text": "Which?", "suggested_answers": "CS"}],
        [{"label": "Branch", "text": "Which?", "suggested_answers": [1, None, {}]}],
        [{"label": 5, "text": "Which?", "suggested_answers": ["a"]}],
    ],
)
def test_FR_INT_04_a_malformed_questions_value_is_dropped_not_fatal(tmp_path, bad) -> None:
    extraction = _extract(tmp_path, bad)

    assert extraction.questions == ()
    assert_valid_brief_ok(extraction.brief)


def assert_valid_brief_ok(brief: dict) -> None:
    from tilo_planning.brief import validate_brief

    validate_brief(brief)


def test_FR_INT_04_no_questions_key_means_no_topic_questions(tmp_path) -> None:
    provider = ScriptedModelProvider("large", [ScriptedCall(text=json.dumps(load_brief_fixture("valid_market_scan")))])

    assert extract_brief("x", router=build_test_router(tmp_path, provider)).questions == ()


# --- ranking, the cap and the generic fallback -----------------------------------------------------------------


def test_FR_INT_04_topic_questions_get_ids_labels_and_replace_the_generic_format_and_rules_questions(tmp_path) -> None:
    result = _topic_questions(tmp_path, ["deliverables", "constraints"], TOPIC[:2])

    assert [q.field for q in result.questions] == ["topic_1", "topic_2"]
    assert [q.label for q in result.questions] == ["Branch", "Level"]
    assert result.questions[0].suggested_answers == ("CS", "EC", "ME") and result.questions[0].expected_change == 0.9
    assert result.event is not None and result.event["data"]["question_count"] == 2
    # the replaced generic fields are not asked, and nothing is assumed silently
    assumed = [a for a in result.brief["assumptions"] if a["question"] is None]
    assert {a["assumed"].split(":")[0] for a in assumed} == {"Deliverables", "Constraints"}


def test_FR_INT_04_other_ambiguous_fields_fill_only_the_slots_the_director_left(tmp_path) -> None:
    one = _topic_questions(tmp_path, ["audience", "deadline", "sources"], TOPIC[:1])
    assert [q.field for q in one.questions] == ["topic_1", "sources", "audience"]  # 3 in all; deadline is over the cap
    assert any(a["question"] is None and a["assumed"].startswith("Deadline") for a in one.brief["assumptions"])

    full = _topic_questions(tmp_path, ["audience", "deadline"], TOPIC)
    assert [q.field for q in full.questions] == ["topic_1", "topic_2", "topic_3"] and len(
        full.questions
    ) == MAX_QUESTIONS


def test_FR_INT_04_the_generic_questions_stay_when_the_director_gives_none(tmp_path) -> None:
    result = _topic_questions(tmp_path, ["deliverables", "constraints"], [])

    assert [q.field for q in result.questions] == ["deliverables", "constraints"]
    assert all(q.label is None for q in result.questions)


def test_FR_INT_04_a_clear_task_with_topic_questions_that_are_not_ambiguous_fields_still_asks_them(tmp_path) -> None:
    result = _topic_questions(tmp_path, [], TOPIC[:2])

    assert len(result.questions) == 2
    assert_valid_event_for(result)


def assert_valid_event_for(result) -> None:
    assert result.event is not None and result.event["type"] == "plan.questions_asked"


def test_FR_INT_05_memory_still_runs_first_for_the_generic_fields(tmp_path) -> None:
    memory = InMemoryPreferenceStore()
    memory.set_preference(
        "audience", "Engineers", ref="m1", recorded_at="2026-10-01T00:00:00.000Z", origin_cost=2, lookup_cost=0
    )

    result = _topic_questions(tmp_path, ["audience", "deadline"], TOPIC[:1], memory=memory)

    assert [e["type"] for e in result.memory_hit_events] == ["memory.hit"]
    assert result.brief["audience"] == "Engineers"
    assert [q.field for q in result.questions] == ["topic_1", "deadline"]


# --- answers and skips -----------------------------------------------------------------------------------------


def _ask(tmp_path):
    return _topic_questions(tmp_path, [], TOPIC[:3])


def test_FR_INT_04_answering_with_the_guess_or_another_suggestion_records_a_label_value_constraint(tmp_path) -> None:
    result = _ask(tmp_path)
    branch, level, _hours = result.questions

    guess = apply_answer(result.brief, branch, "CS", today=TODAY)
    other = apply_answer(guess, level, "some revision", today=TODAY)

    assert guess["constraints"][-1] == "Branch: CS"
    assert other["constraints"][-2:] == ["Branch: CS", "Level: some revision"]


def test_FR_INT_04_a_typed_answer_is_cleaned_clipped_and_must_say_something(tmp_path) -> None:
    result = _ask(tmp_path)
    branch = result.questions[0]

    typed = apply_answer(result.brief, branch, "  Civil <i>engineering</i> \x07 " + "z" * 400, today=TODAY)
    line = typed["constraints"][-1]
    assert line.startswith("Branch: Civil engineering z")
    assert len(line) <= 300 and "<" not in line and "\x07" not in line
    for empty in ("", "   ", "<>", "\x00"):
        with pytest.raises(BriefValidationError):
            apply_answer(result.brief, branch, empty, today=TODAY)


def test_FR_INT_04_skipping_a_topic_question_records_the_assumption_and_uses_it(tmp_path, repo_root, registry) -> None:
    result = _ask(tmp_path)
    level = result.questions[1]

    skipped = record_assumption(result.brief, level)

    assert skipped["assumptions"][-1] == {"question": level.text, "assumed": "Level: beginner"}
    assert skipped["constraints"][-1] == "Level: beginner", "the assumption is the value the plan uses (BQ-97)"
    assert_valid_brief(repo_root, registry, skipped)


STATED = ["Budget: under 500", "Level: beginner"]


def _stated_brief(tmp_path, labels):
    """A brief whose own task already stated two `Label: value` constraints, and a Director that asks `labels`."""
    questions = [
        {"label": label, "text": f"{label}?", "suggested_answers": ["2000", "x"], "expected_change": 0.9 - n / 10}
        for n, label in enumerate(labels)
    ]
    extraction = _extract(tmp_path, questions, constraints=STATED)
    result = generate_questions(
        extraction.brief,
        ["deliverables", "constraints"],
        memory=make_no_memory(),
        base=sample_event_base(),
        seq=2,
        topic_questions=extraction.questions,
    )
    return extraction.brief, result


@pytest.mark.parametrize("label", ["Budget", "budget", "BUDGET", "Level", "level"])
def test_FR_INT_04_a_label_that_collides_with_a_stated_constraint_is_dropped_and_the_generic_questions_fill_in(
    tmp_path, label
) -> None:
    brief, result = _stated_brief(tmp_path, [label])

    assert [q.field for q in result.questions] == ["deliverables", "constraints"]  # the generic fallback
    assert result.brief["constraints"] == STATED and brief["constraints"] == STATED


def test_FR_INT_04_only_the_colliding_question_is_dropped_the_others_are_asked_and_never_touch_stated_ones(
    tmp_path,
) -> None:
    brief, result = _stated_brief(tmp_path, ["Budget", "Branch", "Hours per day"])

    assert [(q.field, q.label) for q in result.questions] == [("topic_1", "Branch"), ("topic_2", "Hours per day")]
    branch, hours = result.questions
    skipped = record_assumption(result.brief, branch)
    answered = apply_answer(skipped, hours, "3", today=TODAY)
    assert answered["constraints"] == [*STATED, "Branch: 2000", "Hours per day: 3"]  # appended; stated ones intact
    assert answered["constraints"][: len(STATED)] == STATED


@pytest.mark.parametrize("label", ["Assumed", "assumed", "Deliverable wishes", "Audience"])
def test_FR_INT_04_a_reserved_label_is_dropped(tmp_path, label) -> None:
    assert _extract(tmp_path, [{"label": label, "text": "Which?", "suggested_answers": ["a"]}]).questions == ()


def test_FR_INT_04_clean_line_folds_compatibility_forms_before_cleaning() -> None:
    from tilo_planning.brief import clean_line

    assert clean_line("\uff22\uff55\uff44\uff47\uff45\uff54", 30) == "Budget"  # full-width letters
    assert clean_line("\uff1cb\uff1eCS\uff1c/b\uff1e", 30) == "CS"  # full-width angle brackets are tags too


def test_FR_INT_04_the_topic_event_is_a_valid_questions_asked_event(tmp_path, repo_root, registry) -> None:
    assert_valid_event(repo_root, registry, _ask(tmp_path).event)


@pytest.mark.parametrize("char", ["\ufdfa", "\ufb01", "\u2461", "\u3392"])
def test_FR_INT_04_clean_line_is_fast_and_bounded_on_characters_that_expand_under_nfkc(char) -> None:
    import time

    from tilo_planning.brief import ANSWER_MAX, LABEL_MAX, TEXT_MAX, clean_line

    began = time.perf_counter()
    for limit in (LABEL_MAX, ANSWER_MAX, TEXT_MAX, 250):
        out = clean_line(char * 200_000, limit)
        assert out is not None and len(out) <= limit

    assert time.perf_counter() - began < 2.0
