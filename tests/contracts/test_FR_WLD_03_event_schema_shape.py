"""FR-WLD-03 / PRD 9.3 `TiloEvent` v1 shape.

`contracts/event.schema.json` must accept every field the PRD 9.3 table lists -- v, id, seq, ts,
world_id, run_id, type, actor, target, level, district, item, severity, credits, summary, cause,
vis, authz, data, trace -- and its `trace` sub-object must accept model_role, profile, tokens_in,
tokens_out, tool, latency_ms, archive_ref (PRD 9.3's own `trace` cell). See `_events_lib`'s module
docstring for the ambiguities resolved in `sample_event()` (all 20 root fields required per
ADR-0002's "every object shape is a named $defs entry" and card.schema.json's own precedent of
requiring its nullable `gate`/`consent` keys; `trace` itself required with seven nullable fields).
"""

from __future__ import annotations

import copy

import pytest
from _events_lib import EVENT_ROOT_FIELDS, SEVERITIES, TRACE_FIELDS, sample_authz, sample_event
from _lib import errors_for, load_schema


def test_FR_WLD_03_event_schema_exists(repo_root):
    schema = load_schema(repo_root, "event")
    assert schema.get("title") in ("Event", "TiloEvent"), (
        f"FR-WLD-03: contracts/event.schema.json title should be 'Event' or 'TiloEvent', got {schema.get('title')!r}"
    )


def test_FR_WLD_03_minimal_sample_event_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested")
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-WLD-03: a well-formed TiloEvent with every PRD 9.3 field present should validate, "
        f"got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("field", EVENT_ROOT_FIELDS)
def test_FR_WLD_03_event_missing_required_field_is_invalid(repo_root, registry, field):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested")
    del instance[field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-WLD-03: a TiloEvent missing {field!r} must be invalid (PRD 9.3 lists it)"


@pytest.mark.parametrize("field", TRACE_FIELDS)
def test_FR_WLD_03_trace_field_may_be_null(repo_root, registry, field):
    """A non-model event (e.g. world.requested, caused by a person) has nothing to report for
    that trace field."""
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested")
    instance["trace"] = {f: None for f in TRACE_FIELDS}
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-WLD-03: trace with every field null (no model call happened) should validate, "
        f"got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("field", ["level", "district", "item", "cause", "authz"])
def test_FR_WLD_03_nullable_field_accepts_null(repo_root, registry, field):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested")
    instance[field] = None
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-WLD-03: {field!r} must accept null (PRD 9.3), got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize(
    "bad_type",
    ["worldrequested", "world.", ".requested", "World.Requested", "world..requested", "world requested", ""],
)
def test_FR_WLD_03_type_not_family_dot_verb_is_invalid(repo_root, registry, bad_type):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested")
    instance["type"] = bad_type
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-WLD-03: type {bad_type!r} is not of the form family.verb and must be invalid"


def test_FR_WLD_03_summary_over_140_chars_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested", summary="x" * 141)
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-WLD-03: summary over 140 characters must be invalid (PRD 9.3 'summary <= 140')"


def test_FR_WLD_03_summary_at_140_chars_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested", summary="x" * 140)
    errors = errors_for(schema, instance, registry)
    assert not errors, (
        f"FR-WLD-03: summary at exactly 140 characters should be valid, got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("bad_seq", [-1, -100, 1.5, "1", None])
def test_FR_WLD_03_seq_not_a_non_negative_integer_is_invalid(repo_root, registry, bad_seq):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested", seq=bad_seq)
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-WLD-03: seq={bad_seq!r} is not a non-negative integer and must be invalid"


@pytest.mark.parametrize("good_seq", [0, 1, 999999])
def test_FR_WLD_03_seq_non_negative_integer_is_valid(repo_root, registry, good_seq):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested", seq=good_seq)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-WLD-03: seq={good_seq} should be valid, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize(
    "bad_ts",
    [
        "2026-09-29T09:30:00Z",  # no milliseconds
        "2026-09-29T09:30:00.000+05:30",  # not UTC
        "2026-09-29T09:30:00.000",  # no timezone at all
        "2026-09-29 09:30:00.000Z",  # not RFC 3339 T separator
        "not-a-timestamp",
    ],
)
def test_FR_WLD_03_ts_without_ms_or_not_utc_is_invalid(repo_root, registry, bad_ts):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested", ts=bad_ts)
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-WLD-03: ts={bad_ts!r} (no ms or not UTC) must be invalid (PRD 9.3 'RFC 3339 UTC, ms')"


@pytest.mark.parametrize("severity", SEVERITIES)
def test_FR_WLD_03_each_documented_severity_is_valid(repo_root, registry, severity):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested", severity=severity)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-WLD-03: severity={severity!r} should be valid, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("bad_severity", ["critical", "warning", "INFO", "", "fyi ", "gate!"])
def test_FR_WLD_03_severity_outside_six_values_is_invalid(repo_root, registry, bad_severity):
    schema = load_schema(repo_root, "event")
    instance = sample_event("world.requested", severity=bad_severity)
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-WLD-03: severity={bad_severity!r} is outside the six PRD 9.3 values and must be invalid"


def test_FR_WLD_03_authz_object_uses_common_authz_shape(repo_root, registry):
    """PRD 9.3 authz cell (BQ-01): the same shape as common.schema.json#/$defs/authz."""
    schema = load_schema(repo_root, "event")
    instance = sample_event("approval.resolved", authz=sample_authz())
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-WLD-03: a well-formed authz object should validate, got: {[e.message for e in errors][:5]}"

    bad = copy.deepcopy(instance)
    bad["authz"] = {"by": "the_model_itself", "ref": "x", "at": "2026-09-29T09:30:00.000Z"}
    bad_errors = errors_for(schema, bad, registry)
    assert bad_errors, "FR-WLD-03: authz.by must reject a value other than person/policy/team_lead (BQ-01)"
