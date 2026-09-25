"""FR-WLD-03 / PRD 9.3 + 10.4 "Audit": "authz uses common.authz (BQ-01) and is required when the
registry marks the type as a side effect" (ticket P0-03 section 1).

This is the exact case the ticket's own test-scope list names: "a type the registry marks as a
side effect without authz" must be invalid. Every type `contracts/events/registry.yaml` flags
`side_effect: true` must fail `event.schema.json` when `authz` is null; every type flagged
`side_effect: false` must accept `authz: null` (so the rule is genuinely tied to the flag, not
blanket-requiring authz everywhere PRD 10.4's "T3 always needs a person" would not apply, e.g.
`world.started`).
"""

from __future__ import annotations

from _events_lib import load_registry_raw, registry_entries, sample_authz, sample_event
from _lib import errors_for, load_schema


def test_FR_WLD_03_every_side_effect_type_requires_authz(repo_root, registry):
    entries = registry_entries(load_registry_raw(repo_root))
    assert entries, "FR-WLD-03: contracts/events/registry.yaml must exist and list at least one type"
    side_effect_types = [t for t, e in entries.items() if e.get("side_effect") is True]
    assert side_effect_types, "FR-WLD-03: at least one registered type must be flagged side_effect: true"

    schema = load_schema(repo_root, "event")
    failures = []
    for type_ in side_effect_types:
        instance = sample_event(type_, authz=None)
        if not errors_for(schema, instance, registry):
            failures.append(type_)
    assert not failures, (
        f"FR-WLD-03: these registry-marked side-effect types accept a null authz, but must not: {failures}"
    )


def test_FR_WLD_03_side_effect_type_with_authz_is_valid(repo_root, registry):
    entries = registry_entries(load_registry_raw(repo_root))
    side_effect_types = [t for t, e in entries.items() if e.get("side_effect") is True]
    assert side_effect_types, "FR-WLD-03: at least one registered type must be flagged side_effect: true"

    schema = load_schema(repo_root, "event")
    failures = []
    for type_ in side_effect_types:
        instance = sample_event(type_, authz=sample_authz())
        errors = errors_for(schema, instance, registry)
        if errors:
            failures.append((type_, [e.message for e in errors][:1]))
    assert not failures, f"FR-WLD-03: a side-effect event with a well-formed authz must validate, got: {failures}"


def test_FR_WLD_03_non_side_effect_type_allows_null_authz(repo_root, registry):
    entries = registry_entries(load_registry_raw(repo_root))
    non_side_effect_types = [t for t, e in entries.items() if e.get("side_effect") is False]
    assert non_side_effect_types, "FR-WLD-03: at least one registered type must be flagged side_effect: false"

    schema = load_schema(repo_root, "event")
    failures = []
    for type_ in non_side_effect_types:
        instance = sample_event(type_, authz=None)
        errors = errors_for(schema, instance, registry)
        if errors:
            failures.append((type_, [e.message for e in errors][:1]))
    assert not failures, (
        f"FR-WLD-03: a non-side-effect event must not be forced to carry authz, got errors for: {failures}"
    )
