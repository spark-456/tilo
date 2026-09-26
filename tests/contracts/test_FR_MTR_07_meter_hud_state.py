"""FR-MTR-07 (PRD 14.4, 14.5; GitHub issue #12, `spark-456/tilo`, ticket CC-SE).

PRD 14.4: "Credits used ... Credits saved ... Time saved (estimate)" are all shown on the HUD
meter. FR-MTR-07's acceptance test: "Meter updates within 1 s of the event." Issue #12: neither
`apps/web` (renders the meter) nor `packages/metering` (computes the numbers) has one shared shape
for that state, so `contracts/meter.schema.json` is the contract both read and write against.

The "within 1 s" half of the acceptance test is a live-latency property of `apps/web`'s renderer,
not of a static contract -- out of this ticket's scope (CC-SE is "contract requests from SE"); it
belongs to whichever ticket builds the renderer's event subscription. This contract test covers the
half a schema *can* fix: the meter carries `last_seq`, so a client can tell a stale state from a
fresh one, and every field the meter must show is present and typed. `time_saved`'s own fields
(range, method link, steering-measured flag) are FR-MTR-05's concern and are tested in
`test_FR_MTR_05_...py`, to keep one file per requirement ID.

Test-writer split: contracts/meter.schema.json does not exist yet on this branch, so every test
here must fail for that reason.
"""

from __future__ import annotations

import pytest
from _cc_se_lib import list_cc_se_fixtures, sample_meter_state
from _lib import errors_for, load_json, load_schema


def test_FR_MTR_07_meter_schema_exists(repo_root):
    schema = load_schema(repo_root, "meter")
    assert schema.get("title") == "Meter", (
        f"FR-MTR-07: contracts/meter.schema.json title should be 'Meter', got {schema.get('title')!r}"
    )


def test_FR_MTR_07_minimal_sample_meter_state_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "meter")
    errors = errors_for(schema, sample_meter_state(), registry)
    assert not errors, f"FR-MTR-07: a well-formed meter state should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("field", ["run_id", "last_seq", "credits_used", "credits_saved", "time_saved", "budget"])
def test_FR_MTR_07_missing_root_field_is_invalid(repo_root, registry, field):
    """PRD 14.4's table: 'Credits used', 'Credits saved' and 'Time saved (estimate)' are all on
    the HUD meter, plus run_id/last_seq (freshness) and budget (14.1's cap/spent/reserved)."""
    schema = load_schema(repo_root, "meter")
    instance = sample_meter_state()
    del instance[field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-07: a meter state missing {field!r} must be invalid (issue #12: all required)"


def test_FR_MTR_07_additional_root_property_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "meter")
    instance = sample_meter_state()
    instance["extra"] = 1
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MTR-07: additionalProperties must be false at the top level (issue #12)"


def test_FR_MTR_07_last_seq_is_a_non_negative_integer(repo_root, registry):
    """last_seq is how a client (or `apps/web`'s renderer) knows whether its meter state is stale
    relative to the event stream -- FR-MTR-07's '1 s' freshness bound is enforced on top of this."""
    schema = load_schema(repo_root, "meter")
    for bad in (-1, 1.5):
        instance = sample_meter_state()
        instance["last_seq"] = bad
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MTR-07: last_seq={bad!r} must be invalid (issue #12: integer, minimum 0)"


@pytest.mark.parametrize("field", ["cap", "spent", "reserved"])
def test_FR_MTR_07_budget_missing_field_is_invalid(repo_root, registry, field):
    """PRD 14.1's reserve-then-commit state (cap, spent, reserved) must be visible on the meter."""
    schema = load_schema(repo_root, "meter")
    instance = sample_meter_state()
    del instance["budget"][field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-07: budget missing {field!r} must be invalid (issue #12: all required)"


def test_FR_MTR_07_credits_used_and_saved_are_non_negative(repo_root, registry):
    """Unlike time_saved (which can go negative), credits used/saved are `common.schema.json#/$defs/credits`."""
    schema = load_schema(repo_root, "meter")
    for field in ("credits_used", "credits_saved"):
        instance = sample_meter_state()
        instance[field] = -1
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MTR-07: {field}=-1 must be invalid (credits are never negative)"


def test_FR_MTR_07_meter_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_cc_se_fixtures(repo_root, "meter", "valid")
    invalid = list_cc_se_fixtures(repo_root, "meter", "invalid")
    assert valid, "FR-MTR-07: contracts/fixtures/meter/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-MTR-07: contracts/fixtures/meter/invalid/ must contain at least one *.json fixture"


def test_FR_MTR_07_meter_valid_fixtures_pass_the_schema(repo_root, registry):
    fixtures = list_cc_se_fixtures(repo_root, "meter", "valid")
    assert fixtures, "FR-MTR-07: no valid meter fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "meter")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert not errors, (
            f"FR-MTR-07: {path.name} must validate against meter.schema.json, got: {[e.message for e in errors][:3]}"
        )


def test_FR_MTR_07_meter_invalid_fixtures_fail_the_schema(repo_root, registry):
    fixtures = list_cc_se_fixtures(repo_root, "meter", "invalid")
    assert fixtures, "FR-MTR-07: no invalid meter fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "meter")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert errors, f"FR-MTR-07: {path.name} must fail validation against meter.schema.json (name says which rule)"
