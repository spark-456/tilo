"""WORKSPACE-TOOLS, ADR-0048: meeting_host_rpc.schema.json 1.4.0 (the read route /internal/workspace/read), the read
tools' rows in config/autonomy.yaml and config/connectors.yaml, and the read's data.transfer (WT-05). Each fixture
against its message; each tool bound to its own args and result; nothing but the closed result fields crosses."""

from __future__ import annotations

import copy
import json
import pathlib
import re

import jsonschema
import pytest
import yaml
from _lib import errors_for, load_json

BASE = "https://contracts.tilo.example/meeting_host_rpc.schema.json"
FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
REPO = pathlib.Path(__file__).resolve().parents[2]
MESSAGES = ("read_request", "read_answer")
TOOLS = ("search_email", "read_email", "read_events", "list_files", "read_file")
SCOPE = {  # WT-06 and WT-07: the one scope each tool's capability declares; Drive stays on drive.file
    "search_email": ("gmail", "https://www.googleapis.com/auth/gmail.readonly"),
    "read_email": ("gmail", "https://www.googleapis.com/auth/gmail.readonly"),
    "read_events": ("google_calendar", "https://www.googleapis.com/auth/calendar.readonly"),
    "list_files": ("google_drive", "https://www.googleapis.com/auth/drive.file"),
    "read_file": ("google_drive", "https://www.googleapis.com/auth/drive.file"),
}
OUTCOMES_NOT_OK = (
    "not_connected",
    "missing_scope",
    "expired",
    "not_found",
    "too_large",
    "unsupported_type",
    "unavailable",
)
SMUGGLED = ("url", "web_view_link", "access_token", "content_b64", "location", "attendees", "description", "owners")
LABELS = {"Mail search", "1 email", "Calendar events", "Drive file list", "1 Drive file"}
CASES = [
    pytest.param(name, kind, path, id=f"{name}/{kind}/{path.stem}")
    for name in MESSAGES
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / f"meeting_host_rpc.{name}" / kind).glob("*.json"))
]


def _schema() -> dict:
    return load_json(REPO / "contracts" / "meeting_host_rpc.schema.json")


def _errors(registry, name, doc):
    return errors_for({"$ref": f"{BASE}#/$defs/{name}"}, doc, registry)


def _valid(name):
    return [load_json(p) for p in sorted((FIXTURES / f"meeting_host_rpc.{name}" / "valid").glob("*.json"))]


def _oks():
    return [a for a in _valid("read_answer") if a["outcome"] == "ok"]


def test_WORKSPACE_TOOLS_meeting_host_rpc_1_4_adds_the_read_route_and_no_error_code():
    schema = _schema()
    assert tuple(map(int, schema["x-version"].split("."))) >= (1, 4, 0)
    assert {f"#/$defs/{m}" for m in MESSAGES} <= {r["$ref"] for r in schema["anyOf"]}
    assert schema["$defs"]["read_tool"]["enum"] == list(TOOLS)
    assert "read" not in json.dumps(schema["$defs"]["error"]["properties"]["error"]["enum"])
    assert all(_valid(m) and list((FIXTURES / f"meeting_host_rpc.{m}" / "invalid").glob("*.json")) for m in MESSAGES)


@pytest.mark.parametrize(("name", "kind", "path"), CASES)
def test_WORKSPACE_TOOLS_fixture_matches_its_message_schema(registry, name, kind, path):
    doc = load_json(path)
    found = _errors(registry, name, doc)
    if kind == "valid":
        assert not found, f"{path.name}: {[e.message for e in found][:3]}"
        assert not errors_for({"$ref": BASE}, doc, registry), f"{path.name} must also match the root"
    else:
        assert found, f"{path.name} validates but its name says which rule it breaks"


@pytest.mark.parametrize("tool", TOOLS)
def test_WORKSPACE_TOOLS_each_args_def_is_a_closed_self_contained_tool_input_schema(tool):
    args = _schema()["$defs"][f"{tool}_args"]
    assert "$ref" not in json.dumps(args), "the harness validates the model's arguments without a registry"
    assert args["type"] == "object" and args["additionalProperties"] is False
    jsonschema.Draft202012Validator.check_schema(args)
    for request in (r for r in _valid("read_request") if r["tool"] == tool):
        assert jsonschema.Draft202012Validator(args).is_valid(request["args"])
    good = {k: v for r in _valid("read_request") if r["tool"] == tool for k, v in r["args"].items()}
    for field, rule in args["properties"].items():
        if "pattern" in rule:  # python's `$` also matches before a final newline: the `not` closes it
            assert jsonschema.Draft202012Validator(args).is_valid({**good, field: good[field]})
            assert not jsonschema.Draft202012Validator(args).is_valid({**good, field: good[field] + chr(10)}), field


@pytest.mark.parametrize("tool", TOOLS)
def test_WORKSPACE_TOOLS_each_tool_is_an_ungated_T1_read_with_exactly_its_declared_scope(tool):
    connectors = {c["id"]: c for c in yaml.safe_load((REPO / "config/connectors.yaml").read_text(encoding="utf-8"))}
    tiers = yaml.safe_load((REPO / "config/autonomy.yaml").read_text(encoding="utf-8"))["actions"]
    declaring = [c for c in connectors.values() if tool in {a["id"] for a in c["actions"]}]
    assert [c["id"] for c in declaring] == [SCOPE[tool][0]], "one connector declares each read tool"
    action = next(a for a in declaring[0]["actions"] if a["id"] == tool)
    assert (action["gate_type"], action["risk_tier"], action["irreversible"]) == ("none", "T1", False)
    assert action["capability"] in ("read", "list", "search")
    assert tiers[tool] == "T1", "listed, or BQ-44 makes the read T3"
    assert declaring[0]["scopes"][action["capability"]] == [SCOPE[tool][1]]


def test_WORKSPACE_TOOLS_a_result_belongs_to_its_own_tool_only(registry):
    for answer in _oks():
        for other in (t for t in TOOLS if t != answer["tool"]):
            assert _errors(registry, "read_answer", {**answer, "tool": other}), f"{answer['tool']} result as {other}"


@pytest.mark.parametrize("outcome", OUTCOMES_NOT_OK)
def test_WORKSPACE_TOOLS_only_ok_carries_a_result_and_the_grant_time(registry, outcome):
    for answer in _oks():
        assert _errors(registry, "read_answer", {**answer, "outcome": outcome})
        assert not _errors(
            registry, "read_answer", {**answer, "outcome": outcome, "result": None, "connected_at": None}
        )
    assert all(_errors(registry, "read_answer", {**a, "connected_at": None}) for a in _oks())


def _objects(doc):
    yield doc
    for value in doc.values() if isinstance(doc, dict) else doc:
        if isinstance(value, dict | list):
            yield from _objects(value)


@pytest.mark.parametrize("key", SMUGGLED)
def test_WORKSPACE_TOOLS_no_result_object_carries_a_link_token_bytes_or_event_detail(registry, key):
    for answer in _oks():
        for index, node in enumerate(o for o in _objects(answer["result"]) if isinstance(o, dict)):
            smuggled = copy.deepcopy(answer)
            target = [o for o in _objects(smuggled["result"]) if isinstance(o, dict)][index]
            target[key] = "fake-value"
            assert _errors(registry, "read_answer", smuggled), f"{answer['tool']} accepts {key!r} in {sorted(node)}"


def test_WORKSPACE_TOOLS_a_maximal_read_request_fits_the_64_KiB_body(registry):
    biggest = {"user_id": "u_" + "a" * 48, "tool": "search_email", "args": {"query": "q" * 200, "max_results": 10}}
    assert not _errors(registry, "read_request", biggest)
    assert len(json.dumps(biggest).encode("utf-8")) < 65536


def test_WORKSPACE_TOOLS_a_read_is_an_inbound_transfer_stamped_with_the_owners_consent(registry):
    event = load_json(FIXTURES / "events/valid/data.transfer--workspace_read.json")
    assert not errors_for({"$ref": "https://contracts.tilo.example/event.schema.json"}, event, registry)
    data, authz = event["data"], event["authz"]
    assert (data["direction"], data["artifact"], data["outbox_id"], data["risk_tier"]) == ("in", None, None, "T1")
    assert data["action_type"] in TOOLS and event["trace"]["tool"] == data["action_type"]
    assert authz["by"] == "person" and authz["at"] <= event["ts"]
    assert event["item"]["artifact_id"] is None and event["item"]["label"] in LABELS
    assert not re.search(r"@|https?:", json.dumps({k: event[k] for k in ("item", "summary", "data")}))


@pytest.mark.parametrize("name", ["ReadRequest", "ReadAnswer", *(f"{t.title().replace('_', '')}Args" for t in TOOLS)])
def test_WORKSPACE_TOOLS_generated_types_exist(repo_root, name):
    import tilo_contracts

    assert hasattr(tilo_contracts, "MeetingHostRpc" + name), f"run `just contracts-gen` for MeetingHostRpc{name}"
    ts = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    assert re.search(rf"\bexport (?:interface|type) MeetingHostRpc{name}\b", ts)
