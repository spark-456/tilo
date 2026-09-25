"""Shared helpers for ticket P0-02 acceptance tests (PRD 15.2 Contract files).

Not a test module itself (leading underscore keeps pytest from collecting it).
tests/contracts/ has no __init__.py, so pytest's default "prepend" import mode
puts this directory on sys.path when it collects any test_*.py here -- the same
plain-module-import pattern tests/repo already uses, just with helpers split out
because this ticket's tests share a lot more logic (schema loading, $ref
resolution, fixture validation) than tests/repo's did.

Ambiguity resolved per CLAUDE.md ("apply the PRD's stated default, log it, keep
going"): PRD 15.2 lists the eleven contract files as bare names
(`brief.schema.json`, ...) with no subdirectory, and `docs/adr/` has no ADR
placing them elsewhere yet, so the default is that the eleven hand-written
schemas live directly under `contracts/`. `packages/contracts-py/CLAUDE.md` and
`packages/contracts-ts/CLAUDE.md` (written by ticket P0-01, which does not own
`contracts/`) instead say "Reads: contracts/schemas/, contracts/events/", which
would put them one level deeper. Both conventions are checked here
(`find_schema_path`) so ticket P0-02 is free to pick either without an
unrelated test failure; only the CP0 payload (2020-12, $id, x-version, rules
below) is actually asserted. Logged as BQ-12 candidate in the report, not in
docs/open-questions.md, since it does not change any acceptance criterion --
only where the file sits.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

# The CP0 contract set this ticket (P0-02) owns: every file in PRD 15.2's table
# frozen 29 Sep except event.schema.json (ticket P0-03, next) and
# manifest.schema.json / scenario.schema.json (1 Oct) / appspec.schema.json
# (Could, later).
SCHEMA_NAMES: tuple[str, ...] = (
    "common",
    "brief",
    "plan",
    "layout",
    "card",
    "policy",
    "handoff",
    "envelope",
    "skill",
    "connector",
    "providers",
)

SCHEMA_ID_TEMPLATE = "https://contracts.tilo.example/{name}.schema.json"


def contracts_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "contracts"


def find_schema_path(repo_root: pathlib.Path, name: str) -> pathlib.Path:
    """Resolve a schema file's path, trying both layouts documented in the repo.

    Returns the first candidate that exists; if neither does, returns the
    bare-`contracts/` candidate so callers get an unambiguous "file not found"
    assertion naming the default location.
    """
    bare = contracts_dir(repo_root) / f"{name}.schema.json"
    nested = contracts_dir(repo_root) / "schemas" / f"{name}.schema.json"
    if bare.is_file():
        return bare
    if nested.is_file():
        return nested
    return bare


def load_schema(repo_root: pathlib.Path, name: str) -> dict[str, Any]:
    path = find_schema_path(repo_root, name)
    if not path.is_file():
        raise FileNotFoundError(
            f"contracts/{name}.schema.json (or contracts/schemas/{name}.schema.json) does not "
            f"exist -- PRD 15.2 Contract files, ticket P0-02"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def fixtures_dir(repo_root: pathlib.Path, name: str, kind: str) -> pathlib.Path:
    """`kind` is "valid" or "invalid" -- ticket P0-02 section 3."""
    assert kind in ("valid", "invalid")
    return contracts_dir(repo_root) / "fixtures" / name / kind


def list_fixtures(repo_root: pathlib.Path, name: str, kind: str) -> list[pathlib.Path]:
    d = fixtures_dir(repo_root, name, kind)
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_registry(repo_root: pathlib.Path) -> Registry:
    """A referencing.Registry with every *.schema.json under contracts/ loaded,
    keyed by its own declared $id (falling back to a file:// URI so a schema
    missing $id can still be found by callers that key on that URI directly).
    """
    resources: list[tuple[str, Resource]] = []
    for path in sorted(contracts_dir(repo_root).glob("**/*.schema.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def validator_for(schema: dict[str, Any], registry: Registry) -> jsonschema.protocols.Validator:
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    cls.check_schema(schema)
    return cls(schema, registry=registry)


def errors_for(
    schema: dict[str, Any], instance: Any, registry: Registry
) -> list[jsonschema.exceptions.ValidationError]:
    return list(validator_for(schema, registry).iter_errors(instance))
