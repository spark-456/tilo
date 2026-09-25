"""tilo_policy.schemas — every input is checked against contracts/*.schema.json before use."""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"
BASE = "https://contracts.tilo.example/"


@functools.cache
def _registry() -> Registry:
    schemas = [json.loads(p.read_text("utf-8")) for p in sorted(CONTRACTS.glob("**/*.schema.json"))]
    resources = [(s["$id"], Resource.from_contents(s, default_specification=DRAFT202012)) for s in schemas]
    return Registry().with_resources(resources)


@functools.cache
def _validator(ref: str, keys: tuple[str, ...]) -> jsonschema.Draft202012Validator:
    props = {k: {"$ref": f"{ref}#/properties/{k}"} for k in keys}
    schema = {"type": "object", "required": list(keys), "properties": props} if keys else {"$ref": ref}
    return jsonschema.Draft202012Validator(schema, registry=_registry())


def conforms(name: str, instance: Any, *keys: str) -> bool:
    """`instance` is valid against contracts/`name` (a file, optionally `#/$defs/...`). With
    `keys`, only those properties are required and each is checked against the file's own."""
    try:
        return bool(_validator(BASE + name, keys).is_valid(instance))
    except Exception:
        return False


def event_ok(part: Any, types: tuple[str, ...]) -> bool:
    """An event part `{type, authz, data}`: an expected type and its data schema; authz null on
    approval.requested (it never authorises, EV-05), otherwise a valid authz (EV-03)."""
    try:
        reserves = part["type"] == "approval.requested"
        return (
            part["type"] in types
            and conforms(f"events/data/{part['type']}.schema.json", part["data"])
            and (part["authz"] is None if reserves else conforms("common.schema.json#/$defs/authz", part["authz"]))
        )
    except Exception:
        return False
