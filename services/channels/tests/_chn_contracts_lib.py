"""Contract helpers shared by the channels tests: repo paths, the event registry and data-schema checks.

Package-unique module name on purpose (same reason as `_channels_lib.py`): this directory has no
__init__.py and other test directories have their own conftest.py. Nothing here is production logic.
"""

from __future__ import annotations

import functools
import json
import pathlib
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"


@functools.cache
def _registry() -> Registry:
    resources = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data["$id"], Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@functools.cache
def registered_types() -> frozenset[str]:
    reg = yaml.safe_load((CONTRACTS / "events" / "registry.yaml").read_text(encoding="utf-8"))
    types = reg.get("types", reg) if isinstance(reg, dict) else {}
    return frozenset(k for k in types if isinstance(k, str) and "." in k)


def data_errors(event_type: str, data: Any) -> list[str]:
    """Schema errors of an event part's `data` against contracts/events/data/<type>.schema.json."""
    schema = json.loads((CONTRACTS / "events" / "data" / f"{event_type}.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=_registry())
    return [e.message for e in validator.iter_errors(data)]
