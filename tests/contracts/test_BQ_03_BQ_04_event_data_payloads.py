"""BQ-03 and BQ-04 (docs/open-questions.md), ticket P0-03 section 3.

BQ-03: "PRD 14.2 counts Email Autopilot units `reply_handled` and `mail_triaged`, but no event
type in 9.5 carries them." Resolved default: `building.completed` with `data.unit_type` in
{`reply_handled`, `mail_triaged`} (plus any other unit type a district's buildings complete --
14.2 only names the Email Autopilot pair as the motivating example) and `data.unit_count`.

BQ-04: "Card merge and 'timed-out card applies its default and posts a Nudge' (10.3, FR-HIL-02)
have no registered event type." Resolved default: `question.answered` with
`data.answered_by = "default"` and `severity = "nudge"`; gates never time out to go (10.2, 10.3).
"""

from __future__ import annotations

from _events_lib import data_schema_path, sample_event
from _lib import errors_for, load_json, load_schema


def test_BQ_03_building_completed_data_schema_exists(repo_root):
    path = data_schema_path(repo_root, "building.completed")
    assert path.is_file(), (
        "BQ-03: contracts/events/data/building.completed.schema.json must exist (PRD 14.2 "
        "'building.completed (data.unit_type, data.unit_count)')"
    )


def test_BQ_03_building_completed_data_requires_unit_type_and_unit_count(repo_root, registry):
    path = data_schema_path(repo_root, "building.completed")
    assert path.is_file(), "BQ-03: see the data-schema-exists test"
    schema = load_json(path)
    full = {"unit_type": "reply_handled", "unit_count": 3}
    for field in ("unit_type", "unit_count"):
        instance = {k: v for k, v in full.items() if k != field}
        errors = errors_for(schema, instance, registry)
        assert errors, f"BQ-03: building.completed data missing {field!r} must be invalid"


def test_BQ_03_building_completed_reply_handled_is_valid(repo_root, registry):
    schema = load_json(data_schema_path(repo_root, "building.completed"))
    instance = {"unit_type": "reply_handled", "unit_count": 3}
    errors = errors_for(schema, instance, registry)
    assert not errors, f"BQ-03: unit_type='reply_handled' should be valid, got: {[e.message for e in errors][:5]}"


def test_BQ_03_building_completed_mail_triaged_is_valid(repo_root, registry):
    schema = load_json(data_schema_path(repo_root, "building.completed"))
    instance = {"unit_type": "mail_triaged", "unit_count": 12}
    errors = errors_for(schema, instance, registry)
    assert not errors, f"BQ-03: unit_type='mail_triaged' should be valid, got: {[e.message for e in errors][:5]}"


def test_BQ_03_building_completed_unit_count_must_be_a_non_negative_integer(repo_root, registry):
    schema = load_json(data_schema_path(repo_root, "building.completed"))
    for bad_count in (-1, 1.5, "3"):
        instance = {"unit_type": "reply_handled", "unit_count": bad_count}
        errors = errors_for(schema, instance, registry)
        assert errors, f"BQ-03: unit_count={bad_count!r} must be invalid"


def test_BQ_04_question_answered_data_schema_exists(repo_root):
    path = data_schema_path(repo_root, "question.answered")
    assert path.is_file(), "BQ-04: contracts/events/data/question.answered.schema.json must exist"


def test_BQ_04_question_answered_data_allows_answered_by_default(repo_root, registry):
    schema = load_json(data_schema_path(repo_root, "question.answered"))
    instance = {"answered_by": "default"}
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"BQ-04: question.answered data.answered_by='default' should be valid, got: {[e.message for e in errors][:5]}"
    )


def test_BQ_04_timed_out_question_answered_event_is_nudge_severity(repo_root, registry):
    """PRD 10.3: 'the Director applies the default and posts a Nudge saying so.'"""
    event_schema = load_schema(repo_root, "event")
    instance = sample_event("question.answered", severity="nudge", data={"answered_by": "default"})
    errors = errors_for(event_schema, instance, registry)
    assert not errors, (
        f"BQ-04: a question.answered event with severity='nudge' and data.answered_by='default' should "
        f"validate, got: {[e.message for e in errors][:5]}"
    )
