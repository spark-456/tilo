"""PL-02: Vertex answers an untyped property schema (`{}`) with 400 "Request contains an invalid argument" (live probe,
8 Oct 2026: director_schema_no_empty accepted, director_exact rejected), so the sanitizer never sends one."""

from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator
from tilo_planning import approaches, brief, compiler
from tilo_providers.conformance import _SCHEMA as CONFORMANCE_SCHEMA
from tilo_providers.schema_subset import (
    WIRE_SCHEMA_KEY,
    complexity,
    to_gemini_schema,
    unsupported_keywords,
    untyped_schemas,
)


def test_PL_02_an_untyped_optional_property_is_dropped_and_leaves_required() -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {}, "c": {"description": "anything"}},
        "required": ["a", "b"],
    }
    out = to_gemini_schema(schema)
    assert out["properties"] == {"a": {"type": "string"}}
    assert out["required"] == ["a"]
    assert untyped_schemas(out) == []


def test_PL_02_an_untyped_array_item_or_branch_is_sent_as_a_string() -> None:
    out = to_gemini_schema(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {}}, "y": {"anyOf": [{}, {"type": "null"}]}}}
    )
    assert out["properties"]["xs"]["items"] == {"type": "string"}
    assert out["properties"]["y"] == {"type": "string", "nullable": True}  # the untyped branch, then the null collapse
    assert untyped_schemas(out) == []


def test_PL_02_a_wire_schema_hint_replaces_the_node_on_the_wire_only() -> None:
    hint = {"type": "array", "items": {"type": "string"}}
    schema = {"type": "object", "properties": {"gaps": {WIRE_SCHEMA_KEY: hint}}}
    before = copy.deepcopy(schema)
    assert to_gemini_schema(schema)["properties"]["gaps"] == hint
    assert schema == before  # the caller's dict is never mutated
    validator = Draft202012Validator(schema)  # the caller's own validator ignores the keyword: still unconstrained
    values: list[Any] = ["x", 3, None, [1, {"a": 2}], {}]
    assert all(validator.is_valid({"gaps": value}) for value in values)


def test_PL_02_no_router_response_schema_is_sent_with_an_untyped_node() -> None:
    schemas = {
        "brief": brief.output_schema(),
        "approaches": approaches._Reply.model_json_schema(),
        "compiler": compiler._Reply.model_json_schema(),
        "conformance": CONFORMANCE_SCHEMA,
    }
    assert {name: untyped_schemas(to_gemini_schema(s)) for name, s in schemas.items()} == {name: [] for name in schemas}


def test_PL_02_the_director_out_of_scope_is_sent_as_the_list_of_category_and_part_the_code_accepts() -> None:
    sent = to_gemini_schema(brief.output_schema())["properties"]["out_of_scope"]
    assert sent["type"] == "array"
    assert sent["items"]["required"] == ["category", "part"]
    assert set(sent["items"]["properties"]) == {"category", "part"}
    raw = brief.output_schema()["properties"]["out_of_scope"]  # the router's validator still sees it unconstrained
    assert Draft202012Validator(raw).is_valid("a string") and Draft202012Validator(raw).is_valid([{"x": 1}])


def test_PL_02_every_sent_router_schema_is_materially_smaller_and_has_no_bounds_or_null_branches() -> None:
    """The live probe (8 Oct 2026): any ONE of three unrelated reductions made the refused Director schema pass, so the
    limit is Vertex's structured-output complexity budget. Every schema is sent well under what failed (the Director's
    raw schema scored 117; 66 is sent now) and carries nothing the caller validates itself."""
    schemas = {
        "brief": (brief.output_schema(), 80),
        "approaches": (approaches._Reply.model_json_schema(), 70),
        "compiler": (compiler._Reply.model_json_schema(), 40),
        "conformance": (CONFORMANCE_SCHEMA, 10),
    }
    for name, (raw, limit) in schemas.items():
        sent = to_gemini_schema(raw)
        assert complexity(sent) <= limit, (name, complexity(sent))
        assert complexity(sent) <= complexity(raw), name
        assert unsupported_keywords(sent) == [], name  # includes title
        text = str(sent)
        for dropped in ("minItems", "maxItems", "minimum", "maximum", "pattern", "uniqueItems", "'null'"):
            assert dropped not in text, (name, dropped)
    assert complexity(to_gemini_schema(brief.output_schema())) <= 0.6 * complexity(brief.output_schema())


def test_PL_02_a_nullable_branch_is_collapsed_to_nullable_on_the_wire() -> None:
    out = to_gemini_schema(
        {
            "type": "object",
            "properties": {"d": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "when"}},
        }
    )
    assert out["properties"]["d"] == {"type": "string", "nullable": True, "description": "when"}
    assert to_gemini_schema({"type": "object", "properties": {"d": {"type": ["string", "null"]}}})["properties"][
        "d"
    ] == {
        "type": "string",
        "nullable": True,
    }
