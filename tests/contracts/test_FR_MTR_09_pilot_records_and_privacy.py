"""FR-MTR-09 (PRD 2.4, 14.4, 16.5; GitHub issue #11, `spark-456/tilo`, ticket CC-SE).

PRD 14.4: "Pilot accounts tag every run and card with a tester id; the daily diary and exit survey
live in a simple form linked from the app; results are aggregated only." FR-MTR-09's acceptance
test: "Pilot report generated from data with one command." PRD 2.4 EV-G3's pilot rules: "written
consent; no confidential employer or client data; test Google accounts or personal accounts only;
data deleted 30 days after the study unless the tester opts in to keep it." PRD 16.5 (privacy):
pilot records hold tester ids and aggregates, never content.

`contracts/pilot.schema.json` (issue #11) has five `$defs` and, following `common.schema.json`'s
own convention for a contract with no single-instance document, a root sampler with one optional
property per definition (see `_cc_se_lib.py`'s module docstring).

Test-writer split: contracts/pilot.schema.json does not exist yet on this branch, so every test
here must fail for that reason.
"""

from __future__ import annotations

import pytest
from _cc_se_lib import (
    list_cc_se_fixtures,
    sample_pilot_consent,
    sample_pilot_diary_entry,
    sample_pilot_survey_response,
    sample_pilot_tag,
)
from _lib import errors_for, load_schema

DEF_REF = "https://contracts.tilo.example/pilot.schema.json#/$defs/{}"


def _def_schema(name: str) -> dict:
    return {"$ref": DEF_REF.format(name)}


def test_FR_MTR_09_pilot_schema_exists(repo_root):
    schema = load_schema(repo_root, "pilot")
    assert schema.get("title") == "Pilot", (
        f"FR-MTR-09: contracts/pilot.schema.json title should be 'Pilot', got {schema.get('title')!r}"
    )


def test_FR_MTR_09_empty_sampler_is_valid(repo_root, registry):
    """No service ever sends a whole Pilot document -- the root is a sampler, like Common's
    (ADR-0002 decision 3), so `{}` must validate."""
    schema = load_schema(repo_root, "pilot")
    errors = errors_for(schema, {}, registry)
    assert not errors, f"FR-MTR-09: an empty pilot sampler should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize(
    "tester_id",
    ["t_r7k2m9pz", "t_ab123456xyz789"],
)
def test_FR_MTR_09_tester_id_pattern_accepts_pseudonymous_ids(repo_root, registry, tester_id):
    errors = errors_for(_def_schema("tester_id"), tester_id, registry)
    assert not errors, f"FR-MTR-09: {tester_id!r} should match the tester_id pattern (issue #11)"


@pytest.mark.parametrize(
    "tester_id",
    [
        "riya@example.com",  # issue #11: "Pseudonymous, never an email or a name"
        "Riya Sharma",
        "u_owner",  # a real Tilo user id, not a tester id
        "t_ab",  # too short (issue #11: 6-32 chars after t_)
        "T_ABCDEF",  # upper-case is not in [a-z0-9]
    ],
)
def test_FR_MTR_09_tester_id_pattern_rejects_names_emails_and_other_ids(repo_root, registry, tester_id):
    errors = errors_for(_def_schema("tester_id"), tester_id, registry)
    assert errors, f"FR-MTR-09: {tester_id!r} must not match the tester_id pattern (PRD 16.5: pseudonymous only)"


def test_FR_MTR_09_consent_requires_study_EV_G3(repo_root, registry):
    """PRD 2.4 names the pilot study EV-G3; issue #11's consent record is scoped to it."""
    instance = sample_pilot_consent(study="EV-G4")
    errors = errors_for(_def_schema("consent"), instance, registry)
    assert errors, "FR-MTR-09: consent.study must be the constant 'EV-G3'"


@pytest.mark.parametrize("field", ["tester_id", "study", "consented_at", "keep_data", "delete_after"])
def test_FR_MTR_09_consent_missing_field_is_invalid(repo_root, registry, field):
    """PRD 2.4: 'written consent.'"""
    instance = sample_pilot_consent()
    del instance[field]
    errors = errors_for(_def_schema("consent"), instance, registry)
    assert errors, f"FR-MTR-09: consent missing {field!r} must be invalid (issue #11: all required)"


def test_FR_MTR_09_consent_keep_data_true_is_valid(repo_root, registry):
    """PRD 2.4: 'data deleted 30 days after the study unless the tester opts in to keep it.'"""
    instance = sample_pilot_consent(keep_data=True)
    errors = errors_for(_def_schema("consent"), instance, registry)
    assert not errors, f"FR-MTR-09: keep_data=true should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("kind", ["run", "card"])
def test_FR_MTR_09_tag_kind_is_run_or_card(repo_root, registry, kind):
    """PRD 14.4: 'tag every run and card with a tester id.'"""
    instance = sample_pilot_tag(kind=kind)
    errors = errors_for(_def_schema("tag"), instance, registry)
    assert not errors, f"FR-MTR-09: tag kind={kind!r} should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MTR_09_tag_kind_closed_to_run_and_card(repo_root, registry):
    instance = sample_pilot_tag(kind="artifact")
    errors = errors_for(_def_schema("tag"), instance, registry)
    assert errors, "FR-MTR-09: tag.kind must be closed to 'run' | 'card' (issue #11)"


def test_FR_MTR_09_diary_entry_day_is_1_to_3(repo_root, registry):
    """PRD 2.4: '3 days' pilot."""
    for bad in (0, 4):
        instance = sample_pilot_diary_entry(day=bad)
        errors = errors_for(_def_schema("diary_entry"), instance, registry)
        assert errors, f"FR-MTR-09: diary_entry.day={bad} must be invalid (issue #11: 1..3)"


def test_FR_MTR_09_diary_entry_trust_is_1_to_5(repo_root, registry):
    for bad in (0, 6):
        instance = sample_pilot_diary_entry(trust=bad)
        errors = errors_for(_def_schema("diary_entry"), instance, registry)
        assert errors, f"FR-MTR-09: diary_entry.trust={bad} must be invalid (issue #11: 1..5)"


def test_FR_MTR_09_diary_entry_reinvested_is_capped_at_280_characters(repo_root, registry):
    """PRD 2.4: 'what did you do with the time saved?' -- a bounded quote, never free-form content
    (PRD 16.5)."""
    instance = sample_pilot_diary_entry(reinvested="x" * 281)
    errors = errors_for(_def_schema("diary_entry"), instance, registry)
    assert errors, "FR-MTR-09: diary_entry.reinvested must reject more than 280 characters (issue #11)"


def test_FR_MTR_09_diary_entry_minutes_saved_self_is_non_negative(repo_root, registry):
    instance = sample_pilot_diary_entry(minutes_saved_self=-1)
    errors = errors_for(_def_schema("diary_entry"), instance, registry)
    assert errors, "FR-MTR-09: diary_entry.minutes_saved_self must be >= 0 (issue #11)"


def test_FR_MTR_09_survey_response_quote_may_be_null(repo_root, registry):
    """Issue #11: 'quote: string <= 280 | null.'"""
    instance = sample_pilot_survey_response(quote=None, quote_consent=False)
    errors = errors_for(_def_schema("survey_response"), instance, registry)
    assert not errors, f"FR-MTR-09: quote=null should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MTR_09_survey_response_quote_is_capped_at_280_characters(repo_root, registry):
    instance = sample_pilot_survey_response(quote="x" * 281)
    errors = errors_for(_def_schema("survey_response"), instance, registry)
    assert errors, "FR-MTR-09: survey_response.quote must reject more than 280 characters (issue #11)"


def test_FR_MTR_09_survey_response_reinvested_share_is_0_to_1(repo_root, registry):
    for bad in (-0.1, 1.1):
        instance = sample_pilot_survey_response(reinvested_share=bad)
        errors = errors_for(_def_schema("survey_response"), instance, registry)
        assert errors, f"FR-MTR-09: survey_response.reinvested_share={bad} must be invalid (issue #11: 0..1)"


@pytest.mark.parametrize(
    "field",
    ["tester_id", "submitted_at", "trust", "reinvested_share", "reinvested_how", "quote", "quote_consent"],
)
def test_FR_MTR_09_survey_response_missing_field_is_invalid(repo_root, registry, field):
    instance = sample_pilot_survey_response()
    del instance[field]
    errors = errors_for(_def_schema("survey_response"), instance, registry)
    assert errors, f"FR-MTR-09: survey_response missing {field!r} must be invalid (issue #11: all required)"


def test_FR_MTR_09_no_pilot_def_carries_a_name_or_email_field(repo_root):
    """PRD 16.5 / issue #11: pilot records hold tester ids and aggregates, never content. Every
    def's `additionalProperties: false` plus this closed field-name check together guarantee no
    def can carry an email, real name or free-text task description alongside a tester id."""
    schema = load_schema(repo_root, "pilot")
    banned = {"email", "name", "full_name", "task", "content", "message", "transcript"}
    for def_name, definition in schema.get("$defs", {}).items():
        if isinstance(definition, dict) and definition.get("type") == "object":
            fields = set(definition.get("properties", {}))
            hit = fields & banned
            assert not hit, f"FR-MTR-09: pilot.{def_name} must not carry {hit} (PRD 16.5: never content)"


def test_FR_MTR_09_pilot_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_se_fixtures(repo_root, "pilot", "valid")
    invalid = list_cc_se_fixtures(repo_root, "pilot", "invalid")
    assert valid, "FR-MTR-09: contracts/fixtures/pilot/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-MTR-09: contracts/fixtures/pilot/invalid/ must contain at least one *.json fixture"
