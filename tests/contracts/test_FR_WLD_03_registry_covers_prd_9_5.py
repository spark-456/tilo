"""FR-WLD-03 (PRD 9.8): "Every registered event type has a fixture, a mapping and a renderer
test" -- acceptance test "Coverage test at 100% of registered types".

Ticket P0-03 sections 2-4: `contracts/events/registry.yaml` must list every type PRD 9.5's table
names (family column plus the backticked verbs -- parsed at runtime by
`_events_lib.parse_prd_9_5_types`, not hand-copied here, so the test tracks the PRD instead of
drifting from it), validate against `contracts/events/registry.schema.json`, and give each type
exactly one of: family, verb, priority, default_severity, side_effect, world_effect, hud_effect,
story_template, trace_row, data_schema (a path under contracts/events/data/) and fixture (a path
under contracts/fixtures/events/), plus the pillar that emits it.

`test_FR_WLD_03_every_registered_type_has_a_data_schema_and_valid_fixture` is the "100% coverage"
test itself: for every PRD 9.5 type, a `contracts/events/data/<type>.schema.json` file exists and
at least one `contracts/fixtures/events/valid/*.json` fixture carries that `type` and validates
against both `event.schema.json` and its data schema.
"""

from __future__ import annotations

import pathlib

import pytest
from _events_lib import (
    REGISTRY_ENTRY_FIELDS,
    data_schema_path,
    load_registry_raw,
    parse_prd_9_5_types,
    registry_entries,
    registry_schema_path,
    registry_yaml_path,
    valid_event_fixtures_by_type,
)
from _lib import errors_for, load_json, load_schema

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRD_TYPES = parse_prd_9_5_types(_REPO_ROOT)


def test_FR_WLD_03_prd_9_5_parses_at_least_the_documented_families(repo_root):
    types = parse_prd_9_5_types(repo_root)
    families = {t.split(".", 1)[0] for t in types}
    # Every family PRD 9.5 lists, including the two sharing one row ("level, district").
    expected_families = {
        "world",
        "plan",
        "budget",
        "level",
        "district",
        "building",
        "agent",
        "skill",
        "question",
        "meeting",
        "connection",
        "data",
        "channel",
        "artifact",
        "approval",
        "policy",
        "alert",
        "memory",
        "app",
    }
    assert families == expected_families, (
        f"FR-WLD-03: PRD 9.5 table parsing changed families -- expected {sorted(expected_families)}, "
        f"got {sorted(families)}. If the PRD table genuinely changed, this test's expectation needs "
        "updating too."
    )
    assert len(types) == 70, f"FR-WLD-03: expected 70 event types out of PRD 9.5, parsed {len(types)}"


def test_FR_WLD_03_registry_yaml_exists(repo_root):
    assert registry_yaml_path(repo_root).is_file(), (
        "FR-WLD-03: contracts/events/registry.yaml must exist (PRD 15.2, ticket P0-03 section 2)"
    )


def test_FR_WLD_03_registry_schema_exists(repo_root):
    assert registry_schema_path(repo_root).is_file(), (
        "FR-WLD-03: contracts/events/registry.schema.json must exist (ticket P0-03 section 2)"
    )


def test_FR_WLD_03_registry_yaml_validates_against_its_schema(repo_root, registry):
    raw = load_registry_raw(repo_root)
    assert raw is not None, "FR-WLD-03: contracts/events/registry.yaml must exist and parse as YAML"
    schema = load_json(registry_schema_path(repo_root))
    errors = errors_for(schema, raw, registry)
    assert not errors, (
        f"FR-WLD-03: contracts/events/registry.yaml must validate against registry.schema.json, "
        f"got: {[e.message for e in errors][:5]}"
    )


@pytest.mark.parametrize("type_", PRD_TYPES)
def test_FR_WLD_03_every_prd_event_type_is_registered(repo_root, type_):
    entries = registry_entries(load_registry_raw(repo_root))
    assert type_ in entries, (
        f"FR-WLD-03: PRD 9.5 registers {type_!r} but contracts/events/registry.yaml does not list it"
    )


@pytest.mark.parametrize("type_", PRD_TYPES)
def test_FR_WLD_03_registry_entry_has_every_required_field(repo_root, type_):
    entries = registry_entries(load_registry_raw(repo_root))
    entry = entries.get(type_)
    assert entry is not None, f"FR-WLD-03: {type_!r} is not registered (see the registered-type test)"
    missing = [f for f in REGISTRY_ENTRY_FIELDS if f not in entry or entry[f] in (None, "")]
    assert not missing, f"FR-WLD-03: registry entry for {type_!r} is missing {missing}"


@pytest.mark.parametrize("type_", PRD_TYPES)
def test_FR_WLD_03_registry_entry_family_and_verb_match_the_type(repo_root, type_):
    entries = registry_entries(load_registry_raw(repo_root))
    entry = entries.get(type_)
    assert entry is not None, f"FR-WLD-03: {type_!r} is not registered"
    family, verb = type_.split(".", 1)
    assert entry.get("family") == family, f"FR-WLD-03: {type_!r} entry's family must be {family!r}"
    assert entry.get("verb") == verb, f"FR-WLD-03: {type_!r} entry's verb must be {verb!r}"


@pytest.mark.parametrize("type_", [t for t in PRD_TYPES if t.startswith("app.")])
def test_FR_WLD_03_app_family_priority_is_could(repo_root, type_):
    """PRD 9.5: "Family | Types" table row for `app` -- 9.8's requirement table has no `app.*`
    row and 8.6/9.8 mark App Studio Could throughout (9.5 itself says "kiosk (Could)"). Ticket
    P0-03 section 2: "priority (app.* = could)"."""
    entries = registry_entries(load_registry_raw(repo_root))
    entry = entries.get(type_)
    assert entry is not None, f"FR-WLD-03: {type_!r} is not registered"
    assert entry.get("priority") == "could", f"FR-WLD-03: {type_!r} priority must be 'could' (PRD 9.5/9.8)"


@pytest.mark.parametrize("type_", PRD_TYPES)
def test_FR_WLD_03_every_registered_type_has_a_data_schema_and_valid_fixture(repo_root, registry, type_):
    """The FR-WLD-03 100%-coverage acceptance test: a data schema on disk, plus at least one
    valid fixture carrying this `type` that validates against both event.schema.json and that
    data schema."""
    data_path = data_schema_path(repo_root, type_)
    assert data_path.is_file(), (
        f"FR-WLD-03: contracts/events/data/{type_}.schema.json must exist for registered type {type_!r}"
    )
    data_schema = load_json(data_path)

    fixtures_by_type = valid_event_fixtures_by_type(repo_root)
    fixtures = fixtures_by_type.get(type_, [])
    assert fixtures, (
        f'FR-WLD-03: no contracts/fixtures/events/valid/*.json fixture has "type": {type_!r} '
        f"(fixtures found for other types: {len(fixtures_by_type)})"
    )

    event_schema = load_schema(repo_root, "event")
    for path in fixtures:
        instance = load_json(path)
        event_errors = errors_for(event_schema, instance, registry)
        assert not event_errors, (
            f"FR-WLD-03: {path.relative_to(repo_root)} (type {type_!r}) must validate against "
            f"event.schema.json, got: {[e.message for e in event_errors][:3]}"
        )
        data_errors = errors_for(data_schema, instance.get("data"), registry)
        assert not data_errors, (
            f"FR-WLD-03: {path.relative_to(repo_root)} (type {type_!r}) `data` must validate "
            f"against contracts/events/data/{type_}.schema.json, got: {[e.message for e in data_errors][:3]}"
        )
