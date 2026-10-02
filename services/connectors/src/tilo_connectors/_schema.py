"""tilo_connectors._schema — cached validators: outbox (OB-05), connector (FR-CON-01), manifest (FR-CON-10)."""

from __future__ import annotations

import functools
import json
import pathlib
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_CONTRACTS_DIR = pathlib.Path(__file__).resolve().parents[4] / "contracts"  # repo root, four parents up


def _load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(_CONTRACTS_DIR.glob("**/*.schema.json")):
        try:
            data = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@functools.lru_cache(maxsize=1)
def outbox_validator() -> jsonschema.protocols.Validator:
    schema = _load_json(_CONTRACTS_DIR / "outbox.schema.json")
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return cls(schema, registry=_registry())


@functools.lru_cache(maxsize=1)
def connector_validator() -> jsonschema.protocols.Validator:
    schema = _load_json(_CONTRACTS_DIR / "connector.schema.json")
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return cls(schema, registry=_registry())


@functools.lru_cache(maxsize=1)
def manifest_validator() -> jsonschema.protocols.Validator:
    schema = _load_json(_CONTRACTS_DIR / "manifest.schema.json")
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return cls(schema, registry=_registry())
