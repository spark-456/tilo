"""PL-03 / FR-INT-10 prerequisite (issue #124): the router validates model output with jsonschema, whose
`uniqueItems` compares every pair when the items are unsortable. `schema_guard` replaces it with a linear
check wherever jsonschema meets the keyword (#173), so thousands of dicts in a unique array are a schema
failure at once, not a stall, under anyOf and recursion too."""

from __future__ import annotations

import copy
import json
import time
from decimal import Decimal

import jsonschema
import pydantic
import pytest
from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    cascade_models_config,
    prices_config_for,
    write_providers_config,
)
from tilo_providers import schema_guard
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.router import schema_error
from tilo_providers.schema_guard import MESSAGE_CHARS

LIMIT_S = 1.0
_IDS = {"type": "array", "uniqueItems": True, "maxItems": 100000, "items": {"type": "string"}}
_SCHEMA = {
    "type": "object",
    "required": ["ids"],
    "properties": {"ids": _IDS, "nested": {"type": "array", "items": {"$ref": "#/$defs/group"}}},
    "$defs": {"group": {"type": "object", "properties": {"members": {"$ref": "#/$defs/id_list"}}}, "id_list": _IDS},
}


def _response(value) -> GenerateResponse:
    return GenerateResponse(text=json.dumps(value), profile_id="cheap")


def test_PL_03_dict_items_in_a_unique_string_array_fail_schema_in_under_a_second() -> None:
    reply = _response({"ids": [{"k": i} for i in range(5000)]})
    started = time.perf_counter()
    message = schema_error(reply, _SCHEMA)
    assert time.perf_counter() - started < LIMIT_S
    assert message is not None
    assert "/ids/0" in message
    assert "string" in message


def test_PL_03_non_string_item_under_a_local_ref_and_nested_array_fails_fast() -> None:
    reply = _response({"ids": ["a"], "nested": [{"members": ["x", ["y"]]}]})
    started = time.perf_counter()
    message = schema_error(reply, _SCHEMA)
    assert time.perf_counter() - started < LIMIT_S
    assert message is not None
    assert "/nested/0/members/1" in message


def test_PL_03_valid_unique_ids_still_pass() -> None:
    assert schema_error(_response({"ids": ["a", "b", "c"], "nested": [{"members": ["x"]}]}), _SCHEMA) is None


def test_PL_03_duplicate_string_ids_still_fail() -> None:
    message = schema_error(_response({"ids": ["a", "a"]}), _SCHEMA)
    assert message is not None
    assert "non-unique" in message


_SAME = [[{"a": 1, "b": 2}, {"b": 2, "a": 1}], [1, 1.0], [[1, {"x": None}], [1, {"x": None}]]]
_DISTINCT = [[True, 1], [False, 0, None, "", [], {}], [{"a": 1}, {"a": 1.5}, {"a": "1"}]]


@pytest.mark.parametrize(("items", "unique"), [(i, False) for i in _SAME] + [(i, True) for i in _DISTINCT])
def test_PL_03_object_and_untyped_unique_arrays_compare_json_values(items, unique) -> None:
    schema = {"type": "object", "properties": {"untyped": {"type": "array", "uniqueItems": True}}}
    message = schema_error(_response({"untyped": items}), schema)
    assert message is None if unique else "non-unique" in (message or "")


@pytest.mark.parametrize(
    ("item_type", "good", "bad"),
    [("string", "a", 1), ("integer", 3, "3"), ("number", 1.5, True), ("boolean", True, 0), ("null", None, "")],
)
def test_PL_03_scalar_item_types_are_checked(item_type, good, bad) -> None:
    schema = {"type": "array", "uniqueItems": True, "items": {"type": item_type}}
    assert schema_error(_response([good]), schema) is None
    assert (schema_error(_response([good, bad]), schema) or "").startswith("/1: ")


def test_PL_03_cyclic_ref_fails_closed_without_looping() -> None:
    schema = {"$ref": "#/$defs/a", "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}}
    assert schema_error(_response({"x": 1}), schema) == "/: the output could not be validated"


def test_PL_03_pydantic_optional_set_with_3000_dicts_fails_in_under_a_second() -> None:
    class Tagged(pydantic.BaseModel):
        tags: set[str] | None = None

    schema = Tagged.model_json_schema()
    assert "anyOf" in schema["properties"]["tags"]  # the shape the walk-based guard could not reach
    started = time.perf_counter()
    message = schema_error(_response({"tags": [{"k": i} for i in range(3000)]}), schema)
    assert time.perf_counter() - started < LIMIT_S
    assert message is not None


def test_PL_03_unique_array_120_levels_deep_in_a_recursive_schema_takes_under_a_second() -> None:
    node_schema = {"type": "object", "properties": {"child": {"$ref": "#/$defs/node"}, "tags": {"uniqueItems": True}}}
    schema = {"$ref": "#/$defs/node", "$defs": {"node": node_schema}}
    node: dict = {"tags": [{"k": i} for i in range(3000)] + [{"k": 0}]}
    for _ in range(120):
        node = {"child": node}
    started = time.perf_counter()
    message = schema_error(_response(node), schema)
    assert time.perf_counter() - started < LIMIT_S
    assert (message or "").startswith("/child/child/")
    assert "non-unique" in (message or "")


@pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
@pytest.mark.parametrize("value", ["a", 1, 3, 1.5, None, [1, 1], [{"k": 1}, {"k": 1.0}]])
def test_PL_03_bounded_any_of_and_one_of_agree_with_jsonschema(keyword, value) -> None:
    branches = [{"type": "string"}, {"type": "integer"}, {"type": "number", "minimum": 2}]
    schema = {keyword: [*branches, {"type": "array", "uniqueItems": True}]}
    expected = jsonschema.Draft202012Validator(schema).is_valid(value)
    assert (schema_error(_response(value), schema) is None) == expected


def test_PL_03_deeply_nested_model_output_is_not_valid_json() -> None:
    reply = GenerateResponse(text="[" * 100_000 + "]" * 100_000, profile_id="cheap")
    assert (schema_error(reply, _SCHEMA) or "").startswith("not valid JSON")


def test_PL_03_validator_and_schema_check_are_built_once_per_schema_content() -> None:
    schema = {"type": "object", "properties": {"tags": {"anyOf": [{"type": "array"}, {"type": "null"}]}}}
    assert schema_guard.validator(schema) is schema_guard.validator(copy.deepcopy(schema))


@pytest.mark.parametrize(
    "schema",
    [{"anyOf": [{"type": "integer"}, {"type": "null"}]}, {"oneOf": [{"type": "string"}, {"maxLength": 10**6}]}],
)
def test_PL_03_any_of_and_one_of_messages_never_echo_a_value_whole(schema) -> None:
    errors = list(schema_guard.validator(schema).iter_errors("x" * 100_000))
    assert len(errors) == 1
    assert len(errors[0].message) < 200


def test_PL_03_unique_items_compares_decimals_by_value() -> None:
    check = schema_guard.validator({"uniqueItems": True})
    assert [e.validator for e in check.iter_errors([Decimal("1"), Decimal("1.0")])] == ["uniqueItems"]
    assert [e.validator for e in check.iter_errors([Decimal("1.5"), 1.5, True])] == ["uniqueItems"]
    assert list(check.iter_errors([Decimal("1"), Decimal("2"), True])) == []


def test_PL_03_echoed_values_are_truncated() -> None:
    message = schema_error(_response({"ids": "x" * 100_000}), _SCHEMA) or ""
    assert len(message) <= MESSAGE_CHARS
    assert message.startswith("/ids: ")
    assert message.endswith("is not of type 'array'")


def test_PL_03_cascade_escalates_on_the_guarded_schema_failure(tmp_path) -> None:
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    models_path, prices_path = write_providers_config(
        tmp_path,
        cascade_models_config(),
        prices_config_for({"cheap": (0.1, 0.2), "mid": (0.5, 1.0), "rich": (2.0, 4.0)}),
    )
    config = load_providers_config(models_path, prices_path)
    bad = ScriptedCall(text=json.dumps({"ids": [{"k": i} for i in range(5000)]}))
    cheap = ScriptedModelProvider("cheap", [bad, bad])  # first attempt and its one repair
    mid = ScriptedModelProvider("mid", [ScriptedCall(text='{"ids": ["a", "b"]}')])
    rich = ScriptedModelProvider("rich", [ScriptedCall(text="must never be reached")])
    router = Router(config, provider_for_profile={"cheap": cheap, "mid": mid, "rich": rich}.__getitem__)

    started = time.perf_counter()
    result = router.generate("analyst", GenerateRequest(prompt="List ids.", json_mode=True, response_schema=_SCHEMA))

    assert time.perf_counter() - started < LIMIT_S * 3
    assert result.outcome == "ok"
    assert [a.profile_id for a in result.attempts] == ["cheap", "cheap", "mid"]
    assert [a.outcome for a in result.attempts[:2]] == ["schema_invalid", "schema_invalid"]
    assert rich.calls == []
