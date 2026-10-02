"""PL-03 / FR-INT-10 prerequisite (issue #124): the router validates model output with jsonschema, whose
`uniqueItems` compares every pair when the items are unsortable. A model reply with thousands of dicts in
an array the schema declares as unique string ids must be a schema failure at once, not a stall."""

from __future__ import annotations

import json
import time

import pytest
from conftest import (
    ScriptedCall,
    ScriptedModelProvider,
    cascade_models_config,
    prices_config_for,
    write_providers_config,
)
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.router import schema_error
from tilo_providers.schema_guard import unique_items_violations

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


def test_PL_03_arrays_not_declared_unique_or_not_scalar_are_left_to_the_schema() -> None:
    schema = {
        "type": "object",
        "properties": {
            "free": {"type": "array", "items": {"type": "string"}},
            "objects": {"type": "array", "uniqueItems": True, "items": {"type": "object"}},
            "untyped": {"type": "array", "uniqueItems": True},
        },
    }
    value = {"free": [{"a": 1}], "objects": [{"a": 1}, {"a": 2}], "untyped": [{"a": 1}, 2]}
    assert unique_items_violations(value, schema) == []


@pytest.mark.parametrize(
    ("item_type", "good", "bad"),
    [("string", "a", 1), ("integer", 3, "3"), ("number", 1.5, True), ("boolean", True, 0), ("null", None, "")],
)
def test_PL_03_scalar_item_types_are_checked(item_type, good, bad) -> None:
    schema = {"type": "array", "uniqueItems": True, "items": {"type": item_type}}
    assert unique_items_violations([good], schema) == []
    assert [path for path, _ in unique_items_violations([good, bad], schema)] == ["/1"]


def test_PL_03_cyclic_ref_does_not_loop() -> None:
    schema = {"$ref": "#/$defs/a", "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}}
    assert unique_items_violations({"x": 1}, schema) == []


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
