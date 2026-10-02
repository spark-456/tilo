"""tilo_providers.schema_guard -- a linear pre-check run before jsonschema (issue #124).

jsonschema's `uniqueItems` sorts the items and, when they are unsortable (dicts, lists, mixed types),
falls back to comparing every pair: 100 gates x 200 dicts took 29 s. For an array the schema declares
`uniqueItems` with a scalar item `type`, an item of another type can only fail validation, so
`unique_items_violations` finds it in one pass and the caller reports it as a schema error without
calling `iter_errors`/`validate`. Arrays whose items are containers or untyped are not covered here
(their own maxItems caps are the bound). Only `$ref`, `allOf`, `properties`, `additionalProperties`
and `items` are followed; `anyOf`/`oneOf`/`if` are skipped since a branch that does not apply could
wrongly reject a valid instance."""

from __future__ import annotations

from typing import Any

from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_SCALAR = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer()),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}
_MAX_DEPTH = 200  # instance nesting plus $ref hops; past it the rest is left to jsonschema


def unique_items_violations(
    instance: Any, schema: dict[str, Any], *, registry: Registry | None = None
) -> list[tuple[str, str]]:
    """(JSON pointer, message) for the first item of each `uniqueItems` array whose type is not the
    scalar type its schema declares. `registry` resolves `$ref`s into other schema documents."""
    try:
        resource = Resource.from_contents(schema, default_specification=DRAFT202012)
        uri = schema.get("$id", "urn:tilo:schema-guard")
        registry = (registry or Registry()).with_resource(uri, resource)
    except Exception:  # an unknown dialect or a bad $id: jsonschema reports it
        return []
    found: list[tuple[str, str]] = []
    _walk(instance, schema, registry.resolver(base_uri=uri), "", 0, found)
    return found


def _lookup(ref: str, resolver: Any) -> tuple[Any, Any] | None:
    try:
        resolved = resolver.lookup(ref)
    except Exception:  # unresolvable: jsonschema reports it
        return None
    return resolved.contents, resolved.resolver


def _scalar_type(items: Any, resolver: Any) -> str | None:
    for _ in range(10):
        if not isinstance(items, dict):
            return None
        if isinstance(items.get("type"), str):
            return items["type"] if items["type"] in _SCALAR else None
        if "$ref" not in items or (target := _lookup(items["$ref"], resolver)) is None:
            return None
        items, resolver = target
    return None


def _walk(node: Any, schema: Any, resolver: Any, path: str, depth: int, found: list[tuple[str, str]]) -> None:
    if depth > _MAX_DEPTH or not isinstance(schema, dict) or not isinstance(node, list | dict):
        return
    if "$ref" in schema and (target := _lookup(schema["$ref"], resolver)) is not None:
        _walk(node, target[0], target[1], path, depth + 1, found)
    for sub in schema.get("allOf") or ():
        _walk(node, sub, resolver, path, depth + 1, found)
    if isinstance(node, list):
        _walk_array(node, schema, resolver, path, depth, found)
    else:
        props = schema.get("properties") or {}
        extra = schema.get("additionalProperties")
        for key, value in node.items():
            sub = props.get(key, extra)
            if isinstance(sub, dict):
                _walk(value, sub, resolver, f"{path}/{key}", depth + 1, found)


def _walk_array(node: list[Any], schema: dict[str, Any], resolver: Any, path: str, depth: int, found: list) -> None:
    items = schema.get("items")
    if schema.get("uniqueItems") is True and (kind := _scalar_type(items, resolver)) is not None:
        for i, item in enumerate(node):
            if not _SCALAR[kind](item):
                found.append((f"{path}/{i}", f"item is not of type '{kind}'"))
                return
    if isinstance(items, dict):
        for i, item in enumerate(node):
            _walk(item, items, resolver, f"{path}/{i}", depth + 1, found)
