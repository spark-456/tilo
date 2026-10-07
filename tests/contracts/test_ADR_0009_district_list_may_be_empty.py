"""ADR-0009 amendment 1 (Proposed, 2026-10-07): an empty `vis` is owner-only, event.schema.json 1.2.0.

`$defs.district_list` loses `minItems: 1` and nothing else: the list stays unique and made of district ids, `vis` stays
required, `"all"` stays the only other value and null is still refused. EV-13 (validator) refuses the empty list when
`district` is set, because a list must include the event's own district. PE-12's Desk-world work-item events
(PPL-11c S5) carry `vis: []`, and the harness view writer puts such an event in no scoped view, so only the owner's
full stream holds it (PRD 15.3). The former `invalid/vis_empty.json` relied on `minItems`; it is now
`invalid/vis_null.json`.
"""

from __future__ import annotations

import re
import sys

import pytest
from _lib import errors_for, load_json, load_schema
from tilo_harness.views import redact

VALID = ("work_item.created--desk_owner_only", "work_item.changed--desk_owner_only")
INVALID = ("vis_null", "vis_repeats_a_district", "vis_list_names_all")
STILL_REFUSED = [None, "", "none", "owner", {}, ["all"], [""], [None], ["d1"], ["D12345"], ["D1", "D1"], [["D1"]]]


def _fixture(repo_root, folder, name):
    return load_json(repo_root / f"contracts/fixtures/events/{folder}/{name}.json")


def _rules(repo_root):
    """scripts/contracts_events.py's event_problems and stream_problems, bound to the repo's schemas and registry."""
    sys.path.insert(0, str(repo_root / "scripts"))
    import contracts_codegen
    import contracts_events

    validate = contracts_codegen.validator(contracts_codegen.load_schemas())
    registry = contracts_events.load_registry(repo_root / "contracts")
    return (lambda event: contracts_events.event_problems(event, registry, validate)), contracts_events.stream_problems


def test_ADR_0009_district_list_loses_min_items_and_nothing_else(repo_root):
    schema = load_schema(repo_root, "event")
    major, minor, _ = (int(p) for p in schema["x-version"].split("."))
    assert (major, minor) >= (1, 2), "accepting [] is additive: the next minor after 1.1.0 (ADR-0002)"
    assert major == 1, "not a breaking change"
    district_id = {"$ref": "common.schema.json#/$defs/district_id"}
    assert schema["$defs"]["district_list"] == {"type": "array", "uniqueItems": True, "items": district_id}
    assert schema["$defs"]["vis"]["anyOf"] == [{"const": "all"}, {"$ref": "#/$defs/district_list"}]
    assert "vis" in schema["required"] and schema["properties"]["vis"] == {"$ref": "#/$defs/vis"}
    decision = load_schema(repo_root, "decision")
    assert decision["$defs"]["district_list"]["minItems"] == 1, "a Decision's district scope is another list"


@pytest.mark.parametrize("name", VALID)
def test_ADR_0009_PE_12_a_desk_world_event_with_empty_vis_is_valid(repo_root, name):
    event = _fixture(repo_root, "valid", name)
    assert (event["vis"], event["district"], event["authz"]) == ([], None, None)
    assert event["world_id"].startswith("w_desk_")
    problems, _ = _rules(repo_root)
    assert problems(event) == [], "both schemas and every event-level rule"


def test_ADR_0009_EV_13_an_empty_vis_names_no_district_outside_the_layout(repo_root):
    """A Desk world has no districts (BQ-PPL11B-11), so its layout ids are empty and `[]` is a subset of them."""
    _, stream_problems = _rules(repo_root)
    assert stream_problems([_fixture(repo_root, "valid", name) for name in VALID], set()) == []


def test_ADR_0009_the_former_vis_empty_fixture_is_valid_now(repo_root, registry):
    event = _fixture(repo_root, "invalid", "vis_null")
    assert event["vis"] is None and event["district"] is None
    assert not errors_for(load_schema(repo_root, "event"), event | {"vis": []}, registry)


@pytest.mark.parametrize("name", INVALID)
def test_ADR_0009_SEC_07_each_remaining_vis_rule_has_a_failing_fixture(repo_root, registry, name):
    event = _fixture(repo_root, "invalid", name)
    schema = load_schema(repo_root, "event")
    errors = errors_for(schema, event, registry)
    assert errors and {tuple(e.absolute_path)[:1] for e in errors} == {("vis",)}, "fails on vis and nothing else"
    fixed = [event["district"]] if event["district"] else []
    assert not errors_for(schema, event | {"vis": fixed}, registry)


@pytest.mark.parametrize("vis", STILL_REFUSED, ids=repr)
def test_ADR_0009_SEC_07_nothing_else_about_vis_is_loosened(repo_root, registry, vis):
    event = _fixture(repo_root, "valid", VALID[0]) | {"vis": vis}
    assert errors_for(load_schema(repo_root, "event"), event, registry), f"vis {vis!r} must stay invalid"


def test_ADR_0009_SEC_07_vis_is_still_required(repo_root, registry):
    event = {k: v for k, v in _fixture(repo_root, "valid", VALID[0]).items() if k != "vis"}
    assert errors_for(load_schema(repo_root, "event"), event, registry)


def test_ADR_0009_EV_13_an_empty_vis_with_a_district_breaks_ev_13_only(repo_root):
    event = load_json(repo_root / "contracts/fixtures/events/registry/invalid/ev13_empty_vis_with_district.json")
    assert (event["vis"], event["district"]) == ([], "D1")
    problems, _ = _rules(repo_root)
    found = problems(event)
    assert found and all(p.startswith("EV-13") for p in found), found
    assert problems(event | {"vis": ["D1"]}) == [], "the district's own list is the valid twin"


def test_ADR_0009_SEC_07_the_harness_views_carry_an_empty_vis_event_in_no_scope(repo_root):
    event = _fixture(repo_root, "valid", VALID[0])
    for scope in ("shared", "D1", "D2"):
        assert redact(event, scope, 1, set()) is None, f"scope {scope} must not see an owner-only event"
    assert redact(event | {"vis": "all"}, "shared", 1, set()) is not None, "the check is not vacuous"


def test_ADR_0009_EV_13_rule_and_vis_description_say_empty_is_owner_only(repo_root):
    rules = (repo_root / "contracts/event.rules.md").read_text(encoding="utf-8")
    ev13 = next(line for line in rules.splitlines() if line.startswith("| EV-13 |"))
    assert all(w in ev13 for w in ("empty list", "owner's full stream", "`district` is null", "ADR-0009")), ev13
    description = load_schema(repo_root, "event")["$defs"]["vis"]["description"]
    assert "only the owner's full stream" in description and "allowed only when district is null" in description


def test_ADR_0009_generated_types_accept_an_empty_list(repo_root):
    python = (repo_root / "packages/contracts-py/src/tilo_contracts/__init__.py").read_text(encoding="utf-8")
    typescript = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    assert re.search(r"^type EventDistrictList = list\[DistrictId\]$", python, re.M)
    assert re.search(r"^export type EventDistrictList = DistrictId\[\];$", typescript, re.M)
    decision = r"^type DecisionDistrictList = Annotated\[list\[DistrictId\], Field\(min_length=1\)\]$"
    assert re.search(decision, python, re.M), "a Decision's district scope keeps its minimum"
