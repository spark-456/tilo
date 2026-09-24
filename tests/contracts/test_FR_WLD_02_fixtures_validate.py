"""FR-WLD-02 (ticket P0-02 section 3; PRD 15.2 "Every schema has valid and
invalid fixtures").

For each of the eleven CP0 schemas this ticket owns:
- contracts/fixtures/<name>/valid/*.json has at least one file, and every one
  of them validates against contracts/<name>.schema.json.
- contracts/fixtures/<name>/invalid/*.json has at least one file, and every
  one of them fails validation (that is the point of an invalid fixture; the
  ticket asks that the file name say which rule it breaks, but this test only
  asserts the schema actually rejects it).
"""

from __future__ import annotations

import pytest
from _lib import SCHEMA_NAMES, errors_for, list_fixtures, load_json, load_schema


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_every_schema_has_valid_and_invalid_fixtures(repo_root, name):
    valid = list_fixtures(repo_root, name, "valid")
    invalid = list_fixtures(repo_root, name, "invalid")
    assert valid, f"FR-WLD-02: contracts/fixtures/{name}/valid/ must contain at least one *.json fixture"
    assert invalid, f"FR-WLD-02: contracts/fixtures/{name}/invalid/ must contain at least one *.json fixture"


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_valid_fixtures_pass_their_schema(repo_root, registry, name):
    fixtures = list_fixtures(repo_root, name, "valid")
    assert fixtures, f"FR-WLD-02: no valid fixtures found for {name} -- see the fixtures-exist test"
    schema = load_schema(repo_root, name)
    for fixture_path in fixtures:
        instance = load_json(fixture_path)
        errors = errors_for(schema, instance, registry)
        assert not errors, (
            f"FR-WLD-02: valid fixture {fixture_path.relative_to(repo_root)} must validate against "
            f"{name}.schema.json, but got: {[e.message for e in errors]}"
        )


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_invalid_fixtures_fail_their_schema(repo_root, registry, name):
    fixtures = list_fixtures(repo_root, name, "invalid")
    assert fixtures, f"FR-WLD-02: no invalid fixtures found for {name} -- see the fixtures-exist test"
    schema = load_schema(repo_root, name)
    for fixture_path in fixtures:
        instance = load_json(fixture_path)
        errors = errors_for(schema, instance, registry)
        assert errors, (
            f"FR-WLD-02: invalid fixture {fixture_path.relative_to(repo_root)} must fail validation "
            f"against {name}.schema.json (its file name should say which rule it breaks), but it "
            "validated cleanly"
        )
