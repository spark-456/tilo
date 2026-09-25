"""FR-WLD-03 (ticket P0-03 section 4): "invalid fixtures for the rules above" -- the delivered
`contracts/fixtures/events/invalid/*.json` files (as opposed to the rule assertions in
`test_FR_WLD_03_event_schema_shape.py` and `test_FR_WLD_03_side_effect_requires_authz.py`, which
build their own minimal cases so they do not depend on fixture files existing yet).

Mirrors `test_FR_WLD_02_invalid_fixtures_fail_their_schema` (P0-02): at least one file present,
and every one actually fails -- against event.schema.json, or, if it is shaped enough to pass
that generic check, against its own type's data schema (so a fixture built to break a
per-type `data` rule, e.g. BQ-03's unit_type/unit_count, still counts as invalid).
"""

from __future__ import annotations

from _events_lib import data_schema_path, event_fixtures_dir, list_event_fixtures
from _lib import errors_for, load_json, load_schema


def test_FR_WLD_03_invalid_event_fixtures_directory_has_files(repo_root):
    fixtures = list_event_fixtures(repo_root, "invalid")
    assert fixtures, (
        f"FR-WLD-03: {event_fixtures_dir(repo_root, 'invalid')} must contain at least one *.json fixture "
        "(one per rule in the ticket's test scope: missing field, bad type format, summary > 140, bad seq, "
        "bad ts, bad severity, side-effect without authz)"
    )


def test_FR_WLD_03_every_invalid_event_fixture_actually_fails(repo_root, registry):
    fixtures = list_event_fixtures(repo_root, "invalid")
    assert fixtures, "FR-WLD-03: no invalid event fixtures found -- see the directory-has-files test"
    event_schema = load_schema(repo_root, "event")
    still_valid = []
    for path in fixtures:
        instance = load_json(path)
        event_errors = errors_for(event_schema, instance, registry)
        if not event_errors:
            type_ = instance.get("type") if isinstance(instance, dict) else None
            data_path = data_schema_path(repo_root, type_) if isinstance(type_, str) else None
            if data_path is not None and data_path.is_file():
                data_errors = errors_for(load_json(data_path), instance.get("data"), registry)
                if data_errors:
                    continue
            still_valid.append(path.name)
    assert not still_valid, (
        f"FR-WLD-03: these contracts/fixtures/events/invalid/ files validate cleanly (their file name "
        f"should say which rule they break): {still_valid}"
    )
