"""tilo_providers.schema_subset — cut a JSON Schema down to what Gemini structured output accepts (PL-02).

Sources (read 7 Oct 2026): https://ai.google.dev/gemini-api/docs/structured-output ("a subset of the JSON Schema
specification": type incl. "null" and type lists, properties, required, additionalProperties, enum, format, minimum,
maximum, items, prefixItems, minItems, maxItems, anyOf, $ref, title, description) and, for Vertex AI,
https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output ("Supported schema
fields": anyOf, enum (only string enums), format (date, date-time, duration, time), items, maximum, maxItems, minimum,
minItems, nullable, properties, description, propertyOrdering, required; anything else is ignored, and a complex schema
can be refused with 400 "InvalidArgument"). The two pages overlap in the keywords kept here; neither lists `default`,
`pattern`, `minLength`, `maxLength` or `uniqueItems`, which the live Director schemas carried (HTTP 400, 7 Oct 2026).

Decisions where the pages differ or are silent: `$ref`/`$defs` are inlined (Vertex does not list them), except a
recursive definition, which cannot be inlined and keeps its `$ref` and its own `$defs`; a list `type` becomes `anyOf`
(both pages list `anyOf`, and `{"type": "null"}` is the documented null branch); `const` becomes a one-value `enum`;
`format` stays only for the documented values. Dropped bounds lose nothing: the caller validates every reply itself.
Pure functions; the caller's dict is never mutated."""

from __future__ import annotations

import copy
from typing import Any

ALLOWED_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "anyOf",
        "additionalProperties",
        "title",
        "description",
        "minItems",
        "maxItems",
        "minimum",
        "maximum",
        "format",
        "propertyOrdering",
        "nullable",
    }
)
_REF_KEYWORDS = frozenset({"$ref", "$defs"})  # only a recursive definition keeps them
_FORMATS = frozenset({"date", "date-time", "time", "duration", "int32", "int64", "float", "double"})
_DEFS_PREFIX = "#/$defs/"


def _def_name(ref: Any) -> str | None:
    return ref[len(_DEFS_PREFIX) :] if isinstance(ref, str) and ref.startswith(_DEFS_PREFIX) else None


def _refs_in(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        name = _def_name(node.get("$ref"))
        if name is not None:
            found.add(name)
        for value in node.values():
            found |= _refs_in(value)
    elif isinstance(node, list):
        for value in node:
            found |= _refs_in(value)
    return found


def _recursive_defs(defs: dict[str, Any]) -> set[str]:
    """Definitions that reach themselves through `$ref`s: the ones that cannot be inlined."""
    graph = {name: _refs_in(body) & set(defs) for name, body in defs.items()}
    recursive: set[str] = set()
    for start in defs:
        seen: set[str] = set()
        stack = list(graph[start])
        while stack:
            name = stack.pop()
            if name == start:
                recursive.add(start)
                break
            if name not in seen:
                seen.add(name)
                stack.extend(graph[name])
    return recursive


class _Cleaner:
    def __init__(self, defs: dict[str, Any]) -> None:
        self.defs, self.recursive, self.kept = defs, _recursive_defs(defs), set[str]()

    def clean(self, node: Any) -> Any:
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str):
            name = _def_name(ref)
            if name in self.defs and name not in self.recursive:
                return self.clean({**self.defs[name], **{k: v for k, v in node.items() if k != "$ref"}})
            if name in self.defs:
                self.kept.add(name)
            return {"$ref": ref, **{k: v for k, v in node.items() if k in ("title", "description")}}
        node = self._normalise(node)
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key not in ALLOWED_KEYWORDS:
                continue
            if key == "properties" and isinstance(value, dict):
                out[key] = {name: self.clean(sub) for name, sub in value.items()}  # names are not keywords
            elif key == "anyOf" and isinstance(value, list):
                out[key] = [self.clean(branch) for branch in value]
            elif key in ("items", "additionalProperties"):
                out[key] = self.clean(value)
            elif key == "format":
                if value in _FORMATS:
                    out[key] = value
            else:
                out[key] = value
        return out

    @staticmethod
    def _normalise(node: dict[str, Any]) -> dict[str, Any]:
        node = dict(node)
        if "const" in node and "enum" not in node:
            node["enum"] = [node.pop("const")]
        kind = node.get("type")
        if isinstance(kind, list):
            if len(kind) == 1:
                node["type"] = kind[0]
            elif "anyOf" in node:
                del node["type"]  # the branches already say what is allowed
            else:
                rest = {k: v for k, v in node.items() if k not in ("type", "title", "description")}
                branches = [{"type": "null"} if t == "null" else {**rest, "type": t} for t in kind]
                node = {k: v for k, v in node.items() if k in ("title", "description")} | {"anyOf": branches}
        return node


def to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """A sanitized deep copy of `schema`: only the documented keywords, `$ref` inlined, list `type` as `anyOf`."""
    schema = copy.deepcopy(schema)
    raw_defs = schema.get("$defs")
    cleaner = _Cleaner(raw_defs if isinstance(raw_defs, dict) else {})
    out = cleaner.clean(schema)
    kept: dict[str, Any] = {}
    while pending := cleaner.kept - set(kept):  # cleaning a kept definition can keep another one
        for name in sorted(pending):
            kept[name] = cleaner.clean(cleaner.defs[name])
    if kept:
        out["$defs"] = kept
    return out  # type: ignore[no-any-return]


def unsupported_keywords(schema: Any, path: str = "") -> list[str]:
    """Every keyword (as `path.keyword`) outside the supported subset, at any depth; [] means `schema` is clean."""
    found: list[str] = []
    if not isinstance(schema, dict):
        return found
    for key, value in schema.items():
        here = f"{path}.{key}"
        if key not in ALLOWED_KEYWORDS and key not in _REF_KEYWORDS:
            found.append(here)
        elif key == "type" and isinstance(value, list):
            found.append(here)
        elif key == "format" and value not in _FORMATS:
            found.append(here)
        elif key in ("properties", "$defs") and isinstance(value, dict):
            for name, sub in value.items():
                found += unsupported_keywords(sub, f"{here}.{name}")
        elif key == "anyOf" and isinstance(value, list):
            for index, sub in enumerate(value):
                found += unsupported_keywords(sub, f"{here}[{index}]")
        elif key in ("items", "additionalProperties"):
            found += unsupported_keywords(value, here)
    return found
