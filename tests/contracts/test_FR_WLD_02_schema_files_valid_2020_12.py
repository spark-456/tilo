"""FR-WLD-02 (PRD 15.2 Contract files; ticket P0-02 section 1).

"Fourteen versioned JSON Schemas in `contracts/` are the single source of
truth for every structure that crosses a service boundary; both Python and
TypeScript types are generated from them, and CI fails on any drift."

This ticket (P0-02) owns eleven of those fourteen (the CP0 set except
event.schema.json). Each one must exist, be a valid JSON Schema 2020-12
document, and follow the two conventions the ticket fixes for every file:
`$id https://contracts.tilo.example/<name>.schema.json` and a top-level
`"x-version": "1.0.0"` at CP0, moving to 1.x.y with additive changes (PRD 15.2).
"""

from __future__ import annotations

import json
import re

import jsonschema
import pytest
from _lib import SCHEMA_ID_TEMPLATE, SCHEMA_NAMES, find_schema_path


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_schema_file_exists(repo_root, name):
    path = find_schema_path(repo_root, name)
    assert path.is_file(), (
        f"FR-WLD-02: contracts/{name}.schema.json must exist (PRD 15.2 Contract files) -- tried {path}"
    )


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_schema_is_valid_json_schema_2020_12(repo_root, name):
    path = find_schema_path(repo_root, name)
    assert path.is_file(), f"FR-WLD-02: contracts/{name}.schema.json must exist first"
    schema = json.loads(path.read_text(encoding="utf-8"))

    dialect = schema.get("$schema", "")
    assert "2020-12" in dialect, (
        f"FR-WLD-02: {name}.schema.json must declare the 2020-12 dialect via $schema, got {dialect!r}"
    )
    # Raises jsonschema.exceptions.SchemaError if the document is not a valid
    # 2020-12 meta-schema instance.
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_schema_id_matches_convention(repo_root, name):
    path = find_schema_path(repo_root, name)
    assert path.is_file(), f"FR-WLD-02: contracts/{name}.schema.json must exist first"
    schema = json.loads(path.read_text(encoding="utf-8"))
    expected = SCHEMA_ID_TEMPLATE.format(name=name)
    assert schema.get("$id") == expected, f"FR-WLD-02: {name}.schema.json $id must be {expected}"


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_FR_WLD_02_schema_declares_x_version_major_1(repo_root, name):
    # PRD 15.2: additive changes are minor, so a frozen v1 schema is any 1.x.y
    # (P0-02b moved providers to 1.1.0); a new major needs its own ADR and test.
    path = find_schema_path(repo_root, name)
    assert path.is_file(), f"FR-WLD-02: contracts/{name}.schema.json must exist first"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert re.fullmatch(r"1\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", str(schema.get("x-version"))), (
        f'FR-WLD-02: {name}.schema.json must declare a top-level "x-version" 1.x.y (frozen v1, PRD 15.2 versioning)'
    )
