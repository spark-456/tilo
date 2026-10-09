"""FR-MTG-09, ADR-0032 T1: contracts/meeting_host_rpc.schema.json. Each fixture against its message, closed objects
with no token, OAuth code or Meet link (ADR-0024 decision 4), the 64 KiB and MAX_RECIPIENTS caps, HB-03/05/07."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import pathlib
import re

import pytest
from _lib import errors_for, load_json

BASE = "https://contracts.tilo.example/meeting_host_rpc.schema.json"
FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
MESSAGES = (
    "send_request",
    "send_answer",
    "user_request",
    "status_answer",
    "disconnect_answer",
    "views_answer",
    "error",
)
# ADR-0035 L1 (FR-CON-02) adds eight more messages to the union, tested in
# test_FR_CON_02_ADR35_L1_live_connector_routes_contract.py. Exactly two fields carry a credential on purpose (LC-03).
LIVE_MESSAGES = (
    "start_request",
    "start_answer",
    "callback_request",
    "callback_answer",
    "connection_disconnect_request",
    "connection_disconnect_answer",
    "execute_request",
    "execute_answer",
)
LIVE_CREDENTIAL_FIELDS = {"callback_request": {"code"}, "start_answer": {"authorize_url"}}
CASES = [
    pytest.param(name, kind, path, id=f"{name}/{kind}/{path.stem}")
    for name in MESSAGES
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / f"meeting_host_rpc.{name}" / kind).glob("*.json"))
]
SECRET_KEYS = ("access_token", "refresh_token", "id_token", "code", "client_secret", "join_url", "hangoutLink", "url")


def _errors(registry, name, doc):
    return errors_for({"$ref": f"{BASE}#/$defs/{name}"}, doc, registry)


def _fixtures(name, kind="valid"):
    return [load_json(p) for p in sorted((FIXTURES / f"meeting_host_rpc.{name}" / kind).glob("*.json"))]


def test_FR_MTG_09_meeting_host_rpc_is_a_versioned_2020_12_contract_with_fixtures(contracts_root):
    schema = load_json(contracts_root / "meeting_host_rpc.schema.json")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema" and schema["$id"] == BASE
    assert schema["title"] == "MeetingHostRpc" and re.fullmatch(r"1\.\d+\.\d+", schema["x-version"])
    assert {r["$ref"] for r in schema["anyOf"]} == {f"#/$defs/{m}" for m in (*MESSAGES, *LIVE_MESSAGES)}
    assert all(_fixtures(m) and _fixtures(m, "invalid") for m in MESSAGES), "each message needs both kinds"


@pytest.mark.parametrize(("name", "kind", "path"), CASES)
def test_FR_MTG_09_fixture_matches_its_message_schema(registry, name, kind, path):
    doc = load_json(path)
    found = _errors(registry, name, doc)
    if kind == "valid":
        assert not found, f"{path.name}: {[e.message for e in found][:3]}"
        assert not errors_for({"$ref": BASE}, doc, registry), f"{path.name} must also match the root"
    else:
        assert found, f"{path.name} validates but its name says which rule it breaks"


def test_FR_MTG_09_every_object_is_closed_and_no_field_names_a_secret_or_link(contracts_root):
    defs = load_json(contracts_root / "meeting_host_rpc.schema.json")["$defs"]
    for name, node in defs.items():
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, f"$defs/{name} must be closed"
            bad = [k for k in node["properties"] if re.search(r"token|secret|oauth|code|link|url|key", k)]
            assert set(bad) <= LIVE_CREDENTIAL_FIELDS.get(name, set()), f"$defs/{name} has {bad}"


def _objects(name, doc):
    """Every object of this contract's own in a message: where a smuggled key must be refused."""
    paths = [()]
    if name == "send_request":
        paths += [("entry",), ("evidence",), ("draft",)]
        paths += [("evidence", "reserved_by", "data"), ("evidence", "authorised_by", "data")]
    if name == "send_answer" and doc["receipt"] is not None:
        paths += [("receipt",), ("receipt", "draft")]
    paths += [("parts", i) for i in range(len(doc.get("parts", [])))]
    paths += [("views", i) for i in range(len(doc.get("views", [])))]
    return paths


@pytest.mark.parametrize("name", MESSAGES)
@pytest.mark.parametrize("key", SECRET_KEYS)
def test_FR_MTG_09_no_message_carries_a_token_an_oauth_code_or_a_meet_link(registry, name, key):
    for doc in _fixtures(name):
        for path in _objects(name, doc):
            smuggled = copy.deepcopy(doc)
            node = smuggled
            for step in path:
                node = node[step]
            node[key] = "fake-value"
            assert _errors(registry, name, smuggled), f"{name} accepts {key!r} at {path}"


def _address(i):
    return f"{'a' * (254 - len(f'{i:02d}@example.org'))}{i:02d}@example.org"


def test_FR_MTG_09_recipients_are_capped_at_MAX_RECIPIENTS_and_parts_at_16(registry):
    request = _fixtures("send_request")[0]
    for count, ok in ((1, True), (50, True), (51, False), (0, False)):
        request["entry"]["recipients"] = [_address(i) for i in range(count)]
        assert bool(_errors(registry, "send_request", request)) is not ok, f"{count} recipients"
    part = {"type": "connection.expired", "connector": "meeting_host", "user_id": "u_owner"}
    for count, ok in ((16, True), (17, False)):
        answer = {"revoked_at_provider": False, "parts": [part] * count}
        assert bool(_errors(registry, "disconnect_answer", answer)) is not ok, f"{count} parts"
    assert pytest.importorskip("tilo_connectors.meeting_host").MAX_RECIPIENTS == 50, "the adapter's cap"


def test_FR_MTG_09_a_send_request_at_its_caps_fits_the_64_KiB_body(registry, contracts_root):
    defs = load_json(contracts_root / "meeting_host_rpc.schema.json")["$defs"]
    cap = defs["draft"]["properties"]["content_b64"]["maxLength"]
    assert cap == 4 * -(-32768 // 3), "content_b64 holds at most the base64 of 32 KiB"
    request = _fixtures("send_request")[0]
    request["entry"]["recipients"] = [_address(i) for i in range(50)]
    for event in ("reserved_by", "authorised_by"):
        request["evidence"][event]["summary"] = "s" * 140
    request["draft"]["content_b64"] = "A" * cap
    assert not _errors(registry, "send_request", request)
    assert len(json.dumps(request).encode()) <= 64 * 1024
    request["draft"]["content_b64"] = "A" * (cap + 4)
    assert _errors(registry, "send_request", request), "content_b64 over its cap"


@pytest.mark.parametrize("request_", _fixtures("send_request"), ids=lambda r: str(len(r["entry"]["recipients"])))
def test_FR_MTG_09_valid_send_requests_hold_HB_03_HB_05_and_the_outbox_check(request_):
    entry, evidence, draft = request_["entry"], request_["evidence"], request_["draft"]
    raw = base64.b64decode(draft["content_b64"], validate=True)
    assert hashlib.sha256(raw).hexdigest() == draft["content_sha256"], "HB-03: hash"
    assert {"artifact_id": draft["artifact_id"], "version": draft["version"]} == entry["item"], "HB-03: item"
    document = json.loads(raw)
    assert document["kind"] == "meeting_event" and document["attendees"] == entry["recipients"], "HB-03, MH-11"
    assert document["owner"] == entry["authz"]["ref"] == evidence["world_owner"], "HB-05, MH-11"
    policy = pytest.importorskip("tilo_policy")
    assert policy.check_entry({**copy.deepcopy(evidence), "entry": entry, "transfer": None, "rule": None}) is None


def test_FR_MTG_09_the_valid_sent_receipt_holds_HB_07_against_the_valid_request():
    google = pytest.importorskip("tilo_connectors.adapters._google")
    request = _fixtures("send_request")[0]
    entry, draft = request["entry"], json.loads(base64.b64decode(request["draft"]["content_b64"]))
    [receipt] = [a["receipt"] for a in _fixtures("send_answer") if a["outcome"] == "sent"]
    assert receipt["event_ref"] == google.side_effect_marker(entry) and receipt["draft"] == entry["item"]
    assert (receipt["world_id"], receipt["outbox_id"]) == (entry["world_id"], entry["id"])
    assert (receipt["meeting_id"], receipt["owner"]) == (draft["meeting_id"], draft["owner"])


GENERATED = ["MeetingHostRpc", *("MeetingHostRpc" + "".join(p.title() for p in m.split("_")) for m in MESSAGES)]


@pytest.mark.parametrize("name", GENERATED)
def test_FR_MTG_09_generated_types_exist(repo_root, name):
    import tilo_contracts

    assert hasattr(tilo_contracts, name), f"tilo_contracts.{name} is missing: run `just contracts-gen`"
    ts = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    assert re.search(rf"\bexport (?:interface|type) {name}\b", ts), f"@tilo/contracts {name} is missing"
