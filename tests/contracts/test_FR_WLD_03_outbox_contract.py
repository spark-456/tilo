"""FR-WLD-03 / PRD 8.5, FR-AGT-11, FR-CHN-13, SEC-03 (ticket P0-03 section 5).

`contracts/outbox.schema.json`: id, idempotency_key, world_id, run_id, action_type, connector,
recipients, attachments, modifiers, risk_tier, authz, undo_window_s, scheduled_at, state (queued,
scheduled, sending, sent, cancelled, failed), created_at.

Ticket's rule test: "an entry without an idempotency key or without authz is invalid." The
outbox is what a gate holds (card.schema.json's `gate` $defs entry, CR-09 to CR-12), so
`sample_outbox_entry()` mirrors the connector/recipients shape `contracts/fixtures/card/valid/`
already uses (PRD 8.5 "Side effects go through an outbox, so they happen exactly once";
FR-AGT-11 "Retrying a send step never produces a second email" -- the idempotency key is what
makes that retry safe).
"""

from __future__ import annotations

import pytest
from _events_lib import OUTBOX_REQUIRED_FIELDS, OUTBOX_STATES, sample_outbox_entry
from _lib import contracts_dir, errors_for, load_json, load_schema


def outbox_fixtures_dir(repo_root, kind: str):
    assert kind in ("valid", "invalid")
    return contracts_dir(repo_root) / "fixtures" / "outbox" / kind


def list_outbox_fixtures(repo_root, kind: str):
    d = outbox_fixtures_dir(repo_root, kind)
    return sorted(d.glob("*.json")) if d.is_dir() else []


def test_FR_WLD_03_outbox_schema_exists(repo_root):
    schema = load_schema(repo_root, "outbox")
    assert schema.get("title") == "Outbox", (
        f"FR-WLD-03: contracts/outbox.schema.json title should be 'Outbox', got {schema.get('title')!r}"
    )


def test_FR_WLD_03_minimal_sample_outbox_entry_is_valid(repo_root, registry):
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry()
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-WLD-03: a well-formed outbox entry should validate, got: {[e.message for e in errors][:5]}"


@pytest.mark.parametrize("field", OUTBOX_REQUIRED_FIELDS)
def test_FR_WLD_03_outbox_missing_required_field_is_invalid(repo_root, registry, field):
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry()
    del instance[field]
    errors = errors_for(schema, instance, registry)
    assert errors, f"FR-WLD-03: an outbox entry missing {field!r} must be invalid"


def test_FR_WLD_03_outbox_without_idempotency_key_is_invalid(repo_root, registry):
    """Ticket's rule test, verbatim: 'an entry without an idempotency key ... is invalid.'"""
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry()
    del instance["idempotency_key"]
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-WLD-03: an outbox entry without idempotency_key must be invalid (FR-AGT-11, FR-CHN-13)"


def test_FR_WLD_03_outbox_without_authz_is_invalid(repo_root, registry):
    """Ticket's rule test, verbatim: 'an entry ... without authz is invalid.'"""
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry(authz=None)
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-WLD-03: an outbox entry without authz must be invalid (SEC-03, PRD 10.4)"


@pytest.mark.parametrize("state", OUTBOX_STATES)
def test_FR_WLD_03_each_documented_state_is_valid(repo_root, registry, state):
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry(state=state)
    errors = errors_for(schema, instance, registry)
    assert not errors, f"FR-WLD-03: outbox state={state!r} should be valid, got: {[e.message for e in errors][:5]}"


def test_FR_WLD_03_outbox_state_outside_documented_set_is_invalid(repo_root, registry):
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry(state="in_progress")
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-WLD-03: outbox state must be one of queued, scheduled, sending, sent, cancelled, failed"


def test_FR_WLD_03_outbox_undo_window_is_non_negative(repo_root, registry):
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry(undo_window_s=-1)
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-WLD-03: undo_window_s must be non-negative"


def test_FR_WLD_03_outbox_authz_uses_common_authz_shape(repo_root, registry):
    schema = load_schema(repo_root, "outbox")
    instance = sample_outbox_entry(authz={"by": "the_model_itself", "ref": "x", "at": "2026-09-29T09:30:00.000Z"})
    errors = errors_for(schema, instance, registry)
    assert errors, "FR-WLD-03: outbox authz.by must reject a value other than person/policy/team_lead (BQ-01)"


def test_FR_WLD_03_outbox_fixtures_directory_has_valid_and_invalid_files(repo_root):
    valid = list_outbox_fixtures(repo_root, "valid")
    invalid = list_outbox_fixtures(repo_root, "invalid")
    assert valid, "FR-WLD-03: contracts/fixtures/outbox/valid/ must contain at least one *.json fixture"
    assert invalid, "FR-WLD-03: contracts/fixtures/outbox/invalid/ must contain at least one *.json fixture"


def test_FR_WLD_03_outbox_valid_fixtures_pass_the_schema(repo_root, registry):
    fixtures = list_outbox_fixtures(repo_root, "valid")
    assert fixtures, "FR-WLD-03: no valid outbox fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "outbox")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert not errors, (
            f"FR-WLD-03: {path.name} must validate against outbox.schema.json, got: {[e.message for e in errors][:3]}"
        )


def test_FR_WLD_03_outbox_invalid_fixtures_fail_the_schema(repo_root, registry):
    fixtures = list_outbox_fixtures(repo_root, "invalid")
    assert fixtures, "FR-WLD-03: no invalid outbox fixtures found -- see the fixtures-directory test"
    schema = load_schema(repo_root, "outbox")
    for path in fixtures:
        errors = errors_for(schema, load_json(path), registry)
        assert errors, f"FR-WLD-03: {path.name} must fail validation against outbox.schema.json (name says which rule)"
