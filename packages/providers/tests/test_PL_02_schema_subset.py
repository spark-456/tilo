"""PL-02 live-run fix: the schema sent as `response_json_schema` is cut to Gemini's documented structured-output subset.

Incident (live, 7 Oct 2026): after the schema reached Google as `response_json_schema`, the Director call was refused
with HTTP 400 "Request contains an invalid argument". The brief schema carries `default`, `maxLength`, `minLength`,
`pattern` and `uniqueItems`, and `$defs`/`$ref` and a list `type`, none of which the docs list as supported.
`tilo_providers.schema_subset.to_gemini_schema` returns a sanitized deep copy: only documented keywords stay, `$ref`
is inlined, a list `type` becomes `anyOf`. The planner validates every reply with pydantic, so dropped bounds lose
nothing. Pure functions; no SDK, no network.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_providers.schema_subset import ALLOWED_KEYWORDS, to_gemini_schema, unsupported_keywords

DROPPED = (
    "additionalProperties",
    "default",
    "maxLength",
    "minLength",
    "pattern",
    "uniqueItems",
    "$schema",
    "examples",
    "const_not_a_keyword",
)


def test_PL_02_unsupported_keywords_are_dropped_and_the_caller_dict_is_not_mutated() -> None:
    schema = {
        "type": "object",
        "title": "Brief",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 80, "pattern": "^[a-z]+$", "default": "x"},
            "tags": {"type": "array", "items": {"type": "string"}, "uniqueItems": True, "maxItems": 3, "minItems": 1},
            "n": {"type": "integer", "minimum": 0, "maximum": 5},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    before = copy.deepcopy(schema)
    out = to_gemini_schema(schema)
    assert schema == before, "the caller's dict is never mutated"
    assert out["properties"]["name"] == {"type": "string"}
    assert out["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}  # bounds stay with the caller
    assert out["properties"]["n"] == {"type": "integer"}
    assert out["required"] == ["name"] and "title" not in out
    assert "additionalProperties" not in out, "Vertex's supported-fields page does not list it"
    assert out is not schema and out["properties"] is not schema["properties"]
    assert unsupported_keywords(schema) and unsupported_keywords(out) == []


def test_PL_02_additional_properties_is_dropped_at_every_depth_including_defs_and_items() -> None:
    schema = {
        "$defs": {"D": {"type": "object", "additionalProperties": False, "properties": {"a": {"type": "string"}}}},
        "type": "object",
        "additionalProperties": {"type": "string"},
        "properties": {
            "d": {"$ref": "#/$defs/D"},
            "l": {"type": "array", "items": {"type": "object", "additionalProperties": False}},
        },
    }
    out = to_gemini_schema(schema)
    assert "additionalProperties" not in json.dumps(out)
    assert out["properties"]["l"]["items"] == {"type": "object"}
    assert unsupported_keywords({"type": "object", "additionalProperties": False}) == [".additionalProperties"]


def test_PL_02_a_property_named_like_a_keyword_is_kept() -> None:
    schema = {
        "type": "object",
        "properties": {"default": {"type": "string"}, "pattern": {"type": "string"}, "title": {"type": "string"}},
        "required": ["default"],
    }
    out = to_gemini_schema(schema)
    assert set(out["properties"]) == {"default", "pattern", "title"}
    assert unsupported_keywords(out) == []


def test_PL_02_defs_and_refs_are_inlined_so_the_endpoint_never_needs_ref_support() -> None:
    schema = {
        "$defs": {"Beat": {"type": "object", "properties": {"text": {"type": "string", "maxLength": 9}}}},
        "type": "object",
        "properties": {
            "one": {"$ref": "#/$defs/Beat"},
            "many": {"type": "array", "items": {"$ref": "#/$defs/Beat"}, "maxItems": 2},
            "described": {"$ref": "#/$defs/Beat", "description": "own words"},
        },
    }
    out = to_gemini_schema(schema)
    text = json.dumps(out)
    assert "$ref" not in text and "$defs" not in text
    beat = {"type": "object", "properties": {"text": {"type": "string"}}}
    assert out["properties"]["one"] == beat and out["properties"]["many"]["items"] == beat
    assert out["properties"]["described"] == {**beat, "description": "own words"}


def test_PL_02_a_recursive_ref_stays_a_ref_with_only_its_own_defs() -> None:
    schema = {
        "$defs": {
            "Node": {"type": "object", "properties": {"kids": {"type": "array", "items": {"$ref": "#/$defs/Node"}}}},
            "Unused": {"type": "string"},
        },
        "type": "object",
        "properties": {"root": {"$ref": "#/$defs/Node"}, "plain": {"type": "string"}},
    }
    out = to_gemini_schema(schema)
    assert set(out["$defs"]) == {"Node"}, "only the definitions a kept ref still points at"
    assert out["properties"]["root"] == {"$ref": "#/$defs/Node"}
    assert out["$defs"]["Node"]["properties"]["kids"]["items"] == {"$ref": "#/$defs/Node"}
    assert unsupported_keywords(out) == []
    assert to_gemini_schema(out) == out


def test_PL_02_a_nullable_list_type_is_sent_as_one_type_with_nullable() -> None:
    out = to_gemini_schema({"type": ["string", "null"], "description": "maybe", "maxLength": 4})
    assert out == {"description": "maybe", "type": "string", "nullable": True}
    assert to_gemini_schema({"type": ["string", "integer"]}) == {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    assert unsupported_keywords(out) == []


def test_PL_02_documented_format_values_stay_and_others_go() -> None:
    assert to_gemini_schema({"type": "string", "format": "date-time"}) == {"type": "string", "format": "date-time"}
    assert to_gemini_schema({"type": "string", "format": "email"}) == {"type": "string"}


def test_PL_02_const_becomes_a_one_value_enum() -> None:
    assert to_gemini_schema({"type": "string", "const": "a"}) == {"type": "string", "enum": ["a"]}


def test_PL_02_a_schema_already_in_the_subset_is_unchanged() -> None:
    schema = {
        "type": "object",
        "properties": {"k": {"type": "string", "enum": ["a", "b"]}, "o": {"anyOf": [{"type": "integer"}]}},
        "required": ["k"],
    }
    assert to_gemini_schema(schema) == schema


# --- property-style checks over random schema trees ---------------------------------------------------------------

_TYPES = ["string", "integer", "number", "boolean", "object", "array", "null"]
_SCALARS = st.one_of(st.integers(-3, 3), st.text(max_size=4), st.booleans(), st.none())


def _schemas() -> st.SearchStrategy[dict[str, Any]]:
    leaf = st.fixed_dictionaries(
        {},
        optional={
            "type": st.sampled_from(_TYPES),
            "title": st.text(max_size=5),
            "description": st.text(max_size=5),
            "enum": st.lists(st.text(max_size=3), min_size=1, max_size=3),
            "default": _SCALARS,
            "pattern": st.text(max_size=4),
            "minLength": st.integers(0, 3),
            "maxLength": st.integers(0, 9),
            "uniqueItems": st.booleans(),
            "minimum": st.integers(-3, 3),
            "format": st.sampled_from(["date", "email", "date-time", "uri"]),
            "examples": st.just([1]),
        },
    )

    def extend(children: st.SearchStrategy[dict[str, Any]]) -> st.SearchStrategy[dict[str, Any]]:
        names = st.sampled_from(["a", "b", "default", "pattern", "title", "type"])
        return st.one_of(
            st.builds(
                lambda props, extra: {"type": "object", "properties": props, "required": sorted(props), **extra},
                st.dictionaries(names, children, max_size=3),
                st.fixed_dictionaries({}, optional={"additionalProperties": st.booleans(), "default": _SCALARS}),
            ),
            st.builds(
                lambda item, extra: {"type": "array", "items": item, **extra},
                children,
                st.fixed_dictionaries({}, optional={"uniqueItems": st.booleans(), "maxItems": st.integers(0, 5)}),
            ),
            st.builds(lambda branches: {"anyOf": branches}, st.lists(children, min_size=1, max_size=3)),
        )

    return st.recursive(leaf, extend, max_leaves=10)


@settings(max_examples=150, deadline=None)
@given(_schemas())
def test_PL_02_property_the_output_has_only_allowed_keywords_at_every_depth(schema: dict[str, Any]) -> None:
    before = copy.deepcopy(schema)
    out = to_gemini_schema(schema)
    assert schema == before
    assert unsupported_keywords(out) == []
    assert to_gemini_schema(out) == out, "idempotent"


@settings(max_examples=150, deadline=None)
@given(_schemas())
def test_PL_02_property_type_properties_and_required_are_never_dropped(schema: dict[str, Any]) -> None:
    def walk(src: Any, got: Any) -> None:
        if not isinstance(src, dict):
            return
        for key in ("type", "properties", "required", "items", "enum", "anyOf"):
            if key in src:
                assert key in got, f"{key} was dropped"
        for name, sub in src.get("properties", {}).items():
            if name not in got["properties"]:
                assert not (set(sub) & {"type", "anyOf", "enum", "$ref", "properties", "items"}), (
                    name
                )  # untyped: dropped
                continue
            walk(sub, got["properties"][name])
        if "items" in src:
            walk(src["items"], got["items"])
        for index, sub in enumerate(src.get("anyOf", [])):
            walk(sub, got["anyOf"][index])

    walk(schema, to_gemini_schema(schema))


def test_PL_02_the_allowed_set_is_the_documented_subset() -> None:
    for banned in DROPPED:
        assert banned not in ALLOWED_KEYWORDS
    assert {"type", "properties", "required", "items", "enum", "anyOf"} <= ALLOWED_KEYWORDS
