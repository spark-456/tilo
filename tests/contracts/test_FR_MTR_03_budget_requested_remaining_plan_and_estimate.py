"""FR-MTR-03 (PRD 14.1, 14.5; GitHub issue #9, `spark-456/tilo`, ticket CC-SE).

PRD 14.1: "At 80% of the approved budget the Director raises `budget.requested` with the remaining
plan and a new estimate." FR-MTR-03's acceptance test: "The request card shows remaining plan and
a new estimate." Issue #9: `contracts/events/data/budget.requested.schema.json` is 1.0.0 on this
branch with only `requested`, `spent` and `cap` -- neither the remaining plan nor the new estimate
can travel with the event -- so the request card cannot show them. The proposed additive change
(1.0.0 -> 1.1.0) adds `remaining_units` (the remaining plan, in plan order) and `estimate` (a
`credit_range`), both required (issue #9's stated "Proposed shape"; see `_cc_se_lib.py`'s module
docstring for why this file follows it rather than the issue's "if you prefer, optional"
alternative). `config/metering.yaml`'s `treasury.request_at` (0.80, the 80% threshold itself) is
tested in `test_FR_MTR_02_...py` alongside the rest of that schema.

This is the test-writer split: the schema is still 1.0.0 on this branch, so every test that needs
1.1.0's new fields must fail now for that reason.
"""

from __future__ import annotations

import json

import pytest
from _cc_se_lib import sample_budget_requested_data_v1_1
from _events_lib import data_schema_path, event_fixtures_dir
from _lib import errors_for, load_json

TYPE = "budget.requested"


def _load_budget_requested_schema(repo_root):
    return load_json(data_schema_path(repo_root, TYPE))


def test_FR_MTR_03_budget_requested_schema_is_version_1_1_0(repo_root):
    schema = _load_budget_requested_schema(repo_root)
    assert schema.get("x-version") == "1.1.0", (
        f"FR-MTR-03: events/data/budget.requested.schema.json should be x-version 1.1.0 "
        f"(issue #9, additive), got {schema.get('x-version')!r}"
    )


def test_FR_MTR_03_remaining_units_and_estimate_are_required(repo_root):
    schema = _load_budget_requested_schema(repo_root)
    required = set(schema.get("required", []))
    missing = {"remaining_units", "estimate"} - required
    assert not missing, f"FR-MTR-03: budget.requested data must require {missing} (issue #9, PRD 14.1)"


def test_FR_MTR_03_v1_1_sample_data_is_valid(repo_root, registry):
    schema = _load_budget_requested_schema(repo_root)
    errors = errors_for(schema, sample_budget_requested_data_v1_1(), registry)
    assert not errors, (
        f"FR-MTR-03: a well-formed budget.requested v1.1.0 data payload should validate, "
        f"got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("field", ["remaining_units", "estimate"])
def test_FR_MTR_03_missing_new_field_is_invalid(repo_root, registry, field):
    schema = _load_budget_requested_schema(repo_root)
    instance = sample_budget_requested_data_v1_1()
    del instance[field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-MTR-03: budget.requested data missing {field!r} must be invalid"


def test_FR_MTR_03_remaining_units_entry_needs_unit_id_and_title(repo_root, registry):
    schema = _load_budget_requested_schema(repo_root)
    for field in ("unit_id", "title"):
        instance = sample_budget_requested_data_v1_1()
        del instance["remaining_units"][0][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MTR-03: a remaining_units entry missing {field!r} must be invalid (issue #9)"


def test_FR_MTR_03_remaining_units_caps_at_200_entries(repo_root, registry):
    """Issue #9: `remaining_units` is `maxItems: 200`."""
    schema = _load_budget_requested_schema(repo_root)
    instance = sample_budget_requested_data_v1_1()
    instance["remaining_units"] = [{"unit_id": f"U{i:04d}", "title": "Unit"} for i in range(201)]
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-MTR-03: remaining_units must reject more than 200 entries (issue #9 maxItems)"


def test_FR_MTR_03_estimate_is_a_credit_range_with_min_and_max(repo_root, registry):
    schema = _load_budget_requested_schema(repo_root)
    for field in ("min", "max"):
        instance = sample_budget_requested_data_v1_1()
        del instance["estimate"][field]
        errors = errors_for(schema, instance, registry)
        assert errors, f"FR-MTR-03: estimate missing {field!r} must be invalid (issue #9: credit_range)"


def test_FR_MTR_03_the_registered_event_fixture_matches_v1_1_0(repo_root, registry):
    """PRD 14.1's own example ('the Director asks for 20 more credits; 32 of 40 are spent') is
    fixtured at contracts/fixtures/events/valid/budget.requested.json and named by
    contracts/events/registry.yaml as budget.requested's canonical fixture; once the schema is
    1.1.0, that fixture's `data` must carry the new required fields too, or the registry's own
    fixture check (contracts_events.py, rule EV-xx) and this schema disagree."""
    fixture_path = event_fixtures_dir(repo_root, "valid") / "budget.requested.json"
    assert fixture_path.is_file(), "FR-MTR-03: contracts/fixtures/events/valid/budget.requested.json must exist"
    event = json.loads(fixture_path.read_text(encoding="utf-8"))
    data = event.get("data", {})
    missing = {"remaining_units", "estimate"} - set(data)
    assert not missing, (
        f"FR-MTR-03: the registered budget.requested fixture's data is missing {missing} -- it must "
        "be updated for the 1.1.0 schema, not just left at its 1.0.0 shape"
    )
    schema = _load_budget_requested_schema(repo_root)
    errors = errors_for(schema, data, registry)
    assert not errors, (
        f"FR-MTR-03: the registered budget.requested fixture's data must validate against the 1.1.0 "
        f"schema, got: {[e.message for e in errors][:5]}"
    )
