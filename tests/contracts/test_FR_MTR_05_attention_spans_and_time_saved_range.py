"""FR-MTR-05 (PRD 14.2, 14.5; GitHub issue #10, `spark-456/tilo`, ticket CC-SE).

PRD 14.2: "Steering minutes (intake, questions, cards, take-over) and review minutes (time
deliverables are open before approval) are measured and subtracted." FR-MTR-05's acceptance test:
"Every displayed estimate links to the method and shows its range." This needs two contracts:

1. `contracts/attention.schema.json` (issue #10) -- one measured span of a person's attention,
   written by `apps/web` and channel handlers, so steering and review minutes can be measured at
   all (without it, PRD 14.2's subtraction has nothing to subtract).
2. `contracts/meter.schema.json`'s `time_saved` group (issue #12) -- the range (`low`/`high`) and
   the method link (`method_url`) the acceptance test names; also whether steering time was
   actually measured (`steering_measured`), matching issue #10's "Until it lands" fallback ("the
   time-saved estimate says 'steering time not measured' instead of claiming zero steering").
   `meter.schema.json`'s other fields (`run_id`, `credits_used`, `budget`, ...) are FR-MTR-07's
   concern and are tested in `test_FR_MTR_07_...py`.

Test-writer split: neither schema exists yet on this branch, so every test here must fail for that
reason.
"""

from __future__ import annotations

import pytest
from _cc_se_lib import ATTENTION_KINDS, list_cc_se_fixtures, sample_attention_span, sample_meter_state
from _lib import errors_for, load_schema


def test_FR_MTR_05_attention_schema_exists(repo_root):
    schema = load_schema(repo_root, "attention")
    assert schema.get("title") == "Attention", (
        f"FR-MTR-05: contracts/attention.schema.json title should be 'Attention', got {schema.get('title')!r}"
    )


def test_FR_MTR_05_minimal_sample_attention_span_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "attention")
    errors = errors_for(schema, sample_attention_span(), registry)
    assert not errors, (
        f"FR-MTR-05: a well-formed attention span should validate, got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("field", ["id", "world_id", "run_id", "user", "kind", "started_at", "ended_at", "ref"])
def test_FR_MTR_05_missing_required_field_is_invalid(repo_root, registry, field):
    schema = load_schema(repo_root, "attention")
    instance = sample_attention_span()
    del instance[field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-05: an attention span missing {field!r} must be invalid (issue #10: all required)"


def test_FR_MTR_05_additional_property_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "attention")
    instance = sample_attention_span()
    instance["notes"] = "extra"
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MTR-05: additionalProperties must be false (issue #10)"


@pytest.mark.parametrize("kind", ATTENTION_KINDS)
def test_FR_MTR_05_every_prd_14_2_kind_is_valid(repo_root, registry, kind):
    """PRD 14.2: 'steering minutes (intake, questions, cards, take-over) and review minutes.'"""
    schema = load_schema(repo_root, "attention")
    instance = sample_attention_span(kind=kind)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MTR-05: kind={kind!r} should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MTR_05_unknown_kind_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "attention")
    instance = sample_attention_span(kind="steering")  # not one of issue #10's five closed values
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MTR-05: kind must be a closed enum (issue #10)"


def test_FR_MTR_05_ref_may_be_null_for_intake(repo_root, registry):
    """Issue #10: 'ref: Card id, artifact id or null for intake.'"""
    schema = load_schema(repo_root, "attention")
    instance = sample_attention_span(kind="intake", ref=None)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MTR-05: ref=null for intake should validate, got: {[e.message for e in errors][:5]}"


def test_FR_MTR_05_attention_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_se_fixtures(repo_root, "attention", "valid")
    invalid = list_cc_se_fixtures(repo_root, "attention", "invalid")
    assert valid, "FR-MTR-05: contracts/fixtures/attention/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-MTR-05: contracts/fixtures/attention/invalid/ must contain at least one *.json fixture"


# --- meter.schema.json's time_saved group (issue #12): range and method link -----------------


def test_FR_MTR_05_meter_time_saved_has_range_and_method_url(repo_root, registry):
    schema = load_schema(repo_root, "meter")
    errors = errors_for(schema, sample_meter_state(), registry)
    assert not errors, f"FR-MTR-05: a well-formed meter state should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("field", ["minutes", "low", "high", "steering_measured", "method_url"])
def test_FR_MTR_05_time_saved_missing_field_is_invalid(repo_root, registry, field):
    schema = load_schema(repo_root, "meter")
    instance = sample_meter_state()
    del instance["time_saved"][field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-05: time_saved missing {field!r} must be invalid (issue #12: all required)"


def test_FR_MTR_05_time_saved_minutes_may_be_negative(repo_root, registry):
    """Issue #12: 'Time saved can be negative when steering takes longer than the baseline. It is
    shown honestly, not clamped.'"""
    schema = load_schema(repo_root, "meter")
    instance = sample_meter_state()
    instance["time_saved"] = {**instance["time_saved"], "minutes": -6.5, "low": -12.0, "high": -1.0}
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-MTR-05: negative time_saved must validate (not clamped), got: {[e.message for e in errors][:5]}"
    )


def test_FR_MTR_05_steering_measured_false_when_not_measured(repo_root, registry):
    """Issue #10's fallback: when steering time is not measured, the meter must be able to say so
    honestly rather than default to zero -- `steering_measured: false` must still validate."""
    schema = load_schema(repo_root, "meter")
    instance = sample_meter_state()
    instance["time_saved"]["steering_measured"] = False
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-MTR-05: steering_measured=false should validate, got: {[e.message for e in errors][:5]}"
