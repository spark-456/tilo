"""FR-AGT-07 (PRD 8.3, 13.1, 15.1; GitHub issue #4 sections 1-2, `spark-456/tilo`, ticket CC-SH).

PRD 8.3: "No repeats. Answers become decisions in P7. A new question similar to an answered one
is answered from the decision, with a citation and a log entry." PRD 8.6 acceptance test:
"A near-duplicate question is auto-answered with a citation; EV-14 repeat rate <= 5%."
PRD 15.1: Decision entity, "question, answer, answered by, scope, expiry", stored at
`orgs/{org}/decisions/{decision}`.

Issue #4 proposes `contracts/decision.schema.json` (id, org_id, question, domain, answer,
option_id, answered_by, source, scope, created_at, expires_at, all required,
`additionalProperties: false`) and a `question.answered` data field `decision_id` (ulid or
null), "required non-null exactly when answered_by is decision" -- the event that names which
decision answered a repeat question.

`event.schema.json#/$defs/answer_source` already includes `"decision"` in its enum on this
branch (ticket P0-03), so the event-shape half of this rule is already frozen; only the data
schema field is new. Test-writer split: `contracts/decision.schema.json` does not exist and
`contracts/events/data/question.answered.schema.json` does not yet accept `decision_id`, so
every test here must fail for one of those two reasons.
"""

from __future__ import annotations

import pytest
from _cc_sh_lib import list_cc_sh_fixtures, sample_decision
from _events_lib import data_schema_path, sample_event
from _lib import errors_for, load_json, load_schema

# --- contracts/decision.schema.json shape --------------------------------------------------


def test_FR_AGT_07_decision_schema_exists(repo_root):
    schema = load_schema(repo_root, "decision")
    assert schema.get("title") == "Decision", (
        f"FR-AGT-07: contracts/decision.schema.json title should be 'Decision', got {schema.get('title')!r}"
    )


def test_FR_AGT_07_minimal_sample_decision_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision()
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: a well-formed decision should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "org_id",
        "question",
        "domain",
        "answer",
        "option_id",
        "answered_by",
        "source",
        "scope",
        "created_at",
        "expires_at",
    ],
)
def test_FR_AGT_07_decision_missing_required_field_is_invalid(repo_root, registry, field):
    """Issue #4: 'All fields are required and additionalProperties: false' -- domain, option_id
    and expires_at are nullable but still required keys."""
    schema = load_schema(repo_root, "decision")
    instance = sample_decision()
    del instance[field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-AGT-07: a decision missing {field!r} must be invalid"


def test_FR_AGT_07_decision_additional_property_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision()
    instance["extra"] = "nope"
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-07: decision additionalProperties must be false (issue #4)"


def test_FR_AGT_07_domain_may_be_null(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(domain=None)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: decision.domain: null should validate, got: {[e.message for e in errors][:5]}"


def test_FR_AGT_07_option_id_may_be_null(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(option_id=None)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: decision.option_id: null should validate, got: {[e.message for e in errors][:5]}"


def test_FR_AGT_07_expires_at_may_be_null(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(expires_at=None)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: decision.expires_at: null should validate, got: {[e.message for e in errors][:5]}"


def test_FR_AGT_07_expires_at_may_be_a_timestamp(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(expires_at="2027-09-29T09:30:00.000Z")
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: a real expires_at timestamp should validate, got: {[e.message for e in errors][:5]}"


def test_FR_AGT_07_question_must_be_1_to_500_chars(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    for bad in ("", "x" * 501):
        instance = sample_decision(question=bad)
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-AGT-07: question of length {len(bad)} must be invalid (issue #4: 1..500)"
    instance = sample_decision(question="x" * 500)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: question of length 500 should validate, got: {[e.message for e in errors][:5]}"


def test_FR_AGT_07_answer_must_be_1_to_2000_chars(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    for bad in ("", "x" * 2001):
        instance = sample_decision(answer=bad)
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-AGT-07: answer of length {len(bad)} must be invalid (issue #4: 1..2000)"
    instance = sample_decision(answer="x" * 2000)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: answer of length 2000 should validate, got: {[e.message for e in errors][:5]}"


def test_FR_AGT_07_answered_by_is_never_a_model(repo_root, registry):
    """Issue #4: 'answered_by is the authz shape. by is person or team_lead only, never policy
    or a model.' (Root CLAUDE.md: 'A model never decides authorisation.')"""
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(answered_by={"by": "the_model_itself", "ref": "x", "at": "2026-09-29T09:30:00.000Z"})
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-07: decision.answered_by.by must reject a value that is not person/team_lead"


def test_FR_AGT_07_source_requires_world_run_and_card(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    for field in ("world_id", "run_id", "card_id"):
        instance = sample_decision()
        del instance["source"][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-AGT-07: decision.source missing {field!r} must be invalid"


@pytest.mark.parametrize("worlds", ["all", ["w_village_basic"]])
def test_FR_AGT_07_scope_worlds_accepts_all_or_a_list(repo_root, registry, worlds):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(scope={"worlds": worlds, "districts": "all"})
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-AGT-07: scope.worlds={worlds!r} should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("districts", ["all", ["D1"]])
def test_FR_AGT_07_scope_districts_accepts_all_or_a_list(repo_root, registry, districts):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(scope={"worlds": "all", "districts": districts})
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-AGT-07: scope.districts={districts!r} should validate, got: {[e.message for e in errors][:5]}"
    )


def test_FR_AGT_07_scope_worlds_rejects_an_arbitrary_string(repo_root, registry):
    schema = load_schema(repo_root, "decision")
    instance = sample_decision(scope={"worlds": "some_world", "districts": "all"})
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-07: scope.worlds must be the literal 'all' or an array of world ids, not an arbitrary string"


def test_FR_AGT_07_decision_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_sh_fixtures(repo_root, "decision", "valid")
    invalid = list_cc_sh_fixtures(repo_root, "decision", "invalid")
    assert valid, "FR-AGT-07: contracts/fixtures/decision/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-AGT-07: contracts/fixtures/decision/invalid/ must contain at least one *.json fixture"


def test_FR_AGT_07_decision_valid_fixtures_pass_the_schema(repo_root, registry):
    fixtures = list_cc_sh_fixtures(repo_root, "decision", "valid")
    assert fixtures, "FR-AGT-07: no valid decision fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "decision")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert not errors, (
            f"FR-AGT-07: {path.name} must validate against decision.schema.json, got: {[e.message for e in errors][:3]}"
        )


def test_FR_AGT_07_decision_invalid_fixtures_fail_the_schema(repo_root, registry):
    fixtures = list_cc_sh_fixtures(repo_root, "decision", "invalid")
    assert fixtures, "FR-AGT-07: no invalid decision fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "decision")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert errors, (
            f"FR-AGT-07: {path.name} must fail validation against decision.schema.json (name says which rule)"
        )


# --- question.answered.data.decision_id (issue #4 section 2) -------------------------------


def test_FR_AGT_07_question_answered_data_schema_has_decision_id_property(repo_root):
    path = data_schema_path(repo_root, "question.answered")
    assert path.is_file(), "FR-AGT-07: contracts/events/data/question.answered.schema.json must exist (ticket P0-03)"
    schema = load_json(path)
    props = schema.get("properties", {})
    assert "decision_id" in props, (
        "FR-AGT-07: question.answered data must gain a decision_id property (issue #4 section 2)"
    )


def test_FR_AGT_07_decision_id_null_when_answered_by_is_not_decision(repo_root, registry):
    schema = load_json(data_schema_path(repo_root, "question.answered"))
    instance = {"answered_by": "person", "decision_id": None}
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-AGT-07: answered_by=person with decision_id=null should validate, got: {[e.message for e in errors][:5]}"
    )


def test_FR_AGT_07_decision_id_required_non_null_when_answered_by_is_decision(repo_root, registry):
    schema = load_json(data_schema_path(repo_root, "question.answered"))
    instance = {"answered_by": "decision", "decision_id": "01J8Z3K4M5N6P7Q8R9S0T1V2W5"}
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-AGT-07: answered_by=decision with a decision_id should validate, got: {[e.message for e in errors][:5]}"
    )


def test_FR_AGT_07_decision_id_null_with_answered_by_decision_is_invalid(repo_root, registry):
    """Issue #4: decision_id is 'required non-null exactly when answered_by is decision'."""
    schema = load_json(data_schema_path(repo_root, "question.answered"))
    instance = {"answered_by": "decision", "decision_id": None}
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-07: answered_by=decision with decision_id=null must be invalid (FR-AGT-07 needs a citation)"


def test_FR_AGT_07_decision_id_missing_with_answered_by_decision_is_invalid(repo_root, registry):
    schema = load_json(data_schema_path(repo_root, "question.answered"))
    instance = {"answered_by": "decision"}
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-07: answered_by=decision without a decision_id key at all must be invalid"


def test_FR_AGT_07_decision_id_set_with_answered_by_person_is_invalid(repo_root, registry):
    """The biconditional's other direction: decision_id is non-null 'exactly when'
    answered_by is decision, so a person-answered question must not carry one."""
    schema = load_json(data_schema_path(repo_root, "question.answered"))
    instance = {"answered_by": "person", "decision_id": "01J8Z3K4M5N6P7Q8R9S0T1V2W5"}
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-AGT-07: answered_by=person with a non-null decision_id must be invalid"


def test_FR_AGT_07_full_event_with_decision_citation_is_valid(repo_root, registry):
    """A near-duplicate question auto-answered from a decision (PRD 8.3, 8.6), as a full
    TiloEvent -- EV-14 (contracts/fixtures/events/invalid/ev14_delivered_by_email_without_cause.json
    already exercises a neighbouring EV-14 case; this is the citation itself)."""
    event_schema = load_schema(repo_root, "event")
    instance = sample_event(
        "question.answered",
        summary="Answered from an earlier decision: suppliers already in the CRM may be emailed outside hours.",
        data={"answered_by": "decision", "decision_id": "01J8Z3K4M5N6P7Q8R9S0T1V2W5"},
    )
    errors = errors_for(event_schema, instance, registry)
    msgs = [e.message for e in errors][:5]
    assert not errors, f"FR-AGT-07: a question.answered event citing a decision should validate, got: {msgs}"
