"""FR-CON-02, ADR-0035 L1 (decisions 2 and 6): the four live-connector routes in
contracts/meeting_host_rpc.schema.json 1.2.0 (start, callback, disconnect, execute), their fixtures and caps, and
the google_calendar rows in config/connectors.yaml and config/autonomy.yaml (create_event T1,
create_event_with_guests T3). Rules that compare values (LC-05, LC-07, HB-03) are the routes'; the valid fixtures
are checked against them here the way test_FR_MTG_09_meeting_host_rpc_contract.py checks HB-03."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import pathlib
import re

import pytest
import yaml
from _lib import errors_for, load_json

BASE = "https://contracts.tilo.example/meeting_host_rpc.schema.json"
ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures"
MESSAGES = (
    "start_request",
    "start_answer",
    "callback_request",
    "callback_answer",
    "connection_disconnect_request",
    "connection_disconnect_answer",
    "execute_request",
    "execute_answer",
)
CASES = [
    pytest.param(name, kind, path, id=f"{name}/{kind}/{path.stem}")
    for name in MESSAGES
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / f"meeting_host_rpc.{name}" / kind).glob("*.json"))
]
SECRET_KEYS = ("access_token", "refresh_token", "id_token", "client_secret", "code_verifier", "code", "link", "url")
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"


def _errors(registry, name, doc):
    return errors_for({"$ref": f"{BASE}#/$defs/{name}"}, doc, registry)


def _fixtures(name, kind="valid"):
    return [load_json(p) for p in sorted((FIXTURES / f"meeting_host_rpc.{name}" / kind).glob("*.json"))]


def _yaml(*parts):
    return yaml.safe_load(ROOT.joinpath(*parts).read_text(encoding="utf-8"))


def _ref(item):
    return {"artifact_id": item["artifact_id"], "version": item["version"]}


def test_FR_CON_02_ADR35_L1_is_an_additive_minor_with_every_message_in_the_union_and_fixtured(contracts_root):
    schema = load_json(contracts_root / "meeting_host_rpc.schema.json")
    major, minor, _ = (int(x) for x in schema["x-version"].split("."))
    assert major == 1 and minor >= 2, "the four routes are additive: 1.2.0"
    assert {f"#/$defs/{m}" for m in MESSAGES} <= {r["$ref"] for r in schema["anyOf"]}
    assert all(_fixtures(m) and _fixtures(m, "invalid") for m in MESSAGES), "each message needs both kinds"


@pytest.mark.parametrize(("name", "kind", "path"), CASES)
def test_FR_CON_02_ADR35_L1_fixture_matches_its_message_schema(registry, name, kind, path):
    doc = load_json(path)
    found = _errors(registry, name, doc)
    if kind == "valid":
        assert not found, f"{path.name}: {[e.message for e in found][:3]}"
        assert not errors_for({"$ref": BASE}, doc, registry), f"{path.name} must also match the root"
    else:
        assert found, f"{path.name} validates but its name says which rule it breaks"


def _objects(name, doc):
    """Every object of this contract's own in a message: where a smuggled key must be refused."""
    paths = [()] + [("parts", i) for i in range(len(doc.get("parts", [])))]
    if name == "execute_answer" and doc["result"] is not None:
        paths.append(("result",))
    if name == "execute_request":
        paths += [("entry",), ("evidence",), ("items", 0)]
    return paths


@pytest.mark.parametrize("name", MESSAGES)
@pytest.mark.parametrize("key", SECRET_KEYS)
def test_FR_CON_02_ADR35_L1_no_message_carries_a_token_a_secret_or_a_verifier(registry, name, key):
    if (name, key) == ("callback_request", "code"):
        pytest.skip("code is the callback request's own field (LC-03)")
    for doc in _fixtures(name):
        for path in _objects(name, doc):
            smuggled = copy.deepcopy(doc)
            node = smuggled
            for step in path:
                node = node[step]
            node[key] = "fake-value"
            assert _errors(registry, name, smuggled), f"{name} accepts {key!r} at {path}"


def test_FR_CON_02_ADR35_L1_the_callback_carries_exactly_one_of_code_and_error(registry):
    approved, denied = _fixtures("callback_request")
    assert "code" in approved and "error" in denied
    assert not _errors(registry, "callback_request", approved)
    assert not _errors(registry, "callback_request", denied)
    assert _errors(registry, "callback_request", {**approved, "error": "access_denied"}), "both"
    assert _errors(registry, "callback_request", {k: v for k, v in approved.items() if k != "code"}), "neither"


@pytest.mark.parametrize(
    ("field", "value", "ok"),
    [
        ("state", "a" * 16, True),
        ("state", "a" * 15, False),
        ("state", "a" * 128, True),
        ("state", "a" * 129, False),
        ("state", "A-b_" * 8, True),
        ("code", "4/" + "a" * 510, True),
        ("code", "4/" + "a" * 511, False),
        ("code", "4/0A-fake_code.1~", True),
        ("error", "access_denied", True),
        ("error", "a" * 64, True),
        ("error", "a" * 65, False),
        ("error", "access-denied", False),
    ],
)
def test_FR_CON_02_ADR35_L1_state_code_and_error_words_have_closed_shapes_and_caps(registry, field, value, ok):
    doc = copy.deepcopy(_fixtures("callback_request")[0 if field != "error" else 1])
    doc[field] = value
    assert bool(_errors(registry, "callback_request", doc)) is not ok, f"{field} {value[:20]!r}"


def test_FR_CON_02_ADR35_L1_the_authorize_url_is_google_with_an_encoded_query_and_names_no_secret(registry):
    url = _fixtures("start_answer")[0]["authorize_url"]
    assert url.startswith(AUTH + "?") and "code_challenge=" in url and "code_challenge_method=S256" in url
    for secret in ("client_secret", "code_verifier", "code", "access_token", "refresh_token"):
        assert _errors(registry, "start_answer", {"authorize_url": f"{url}&{secret}=x"}), secret
        assert _errors(registry, "start_answer", {"authorize_url": f"{AUTH}?{secret}=x&{url[len(AUTH) + 1 :]}"}), secret
    pad = 2048 - len(AUTH) - len("?state=")
    assert not _errors(registry, "start_answer", {"authorize_url": f"{AUTH}?state={'a' * pad}"}), "2048 characters"
    assert _errors(registry, "start_answer", {"authorize_url": f"{AUTH}?state={'a' * (pad + 1)}"}), "2049"


def test_FR_CON_02_ADR35_L1_execute_items_attachments_and_earlier_events_are_capped(registry):
    base = _fixtures("execute_request")
    plain = next(r for r in base if len(r["items"]) == 1 and r["evidence"]["reserved_by"])
    with_attachment = next(r for r in base if len(r["items"]) == 2)
    for count, ok in ((1, True), (11, True), (0, False), (12, False)):
        assert bool(_errors(registry, "execute_request", {**plain, "items": [plain["items"][0]] * count})) is not ok
    for count, ok in ((10, True), (11, False)):
        request = copy.deepcopy(with_attachment)
        request["entry"]["attachments"] = [{"artifact_id": f"art_att_{i:02d}", "version": 1} for i in range(count)]
        assert bool(_errors(registry, "execute_request", request)) is not ok, f"{count} attachments"
    policy_path = next(r for r in base if r["evidence"]["reserved_by"] is None)
    applied = policy_path["evidence"]["earlier_applied"][0]
    for count, ok in ((50, True), (51, False)):
        request = copy.deepcopy(policy_path)
        request["evidence"]["earlier_applied"] = [applied] * count
        assert bool(_errors(registry, "execute_request", request)) is not ok, f"{count} earlier events"
        if ok:
            assert len(json.dumps(request).encode()) <= 64 * 1024, "50 earlier events fit the 64 KiB body"


def _declared(connector):
    return next(c for c in _yaml("config", "connectors.yaml") if c["id"] == connector)


@pytest.mark.parametrize("request_", _fixtures("execute_request"), ids=lambda r: r["entry"]["action_type"])
def test_FR_CON_02_ADR35_L1_valid_execute_requests_hold_HB_03_LC_07_and_the_outbox_check(request_):
    entry, evidence, items = request_["entry"], request_["evidence"], request_["items"]
    for item in items:
        raw = base64.b64decode(item["content_b64"], validate=True)
        assert hashlib.sha256(raw).hexdigest() == item["content_sha256"], "HB-03: hash"
    assert [_ref(i) for i in items] == [entry["item"], *entry["attachments"]], "LC-07: the item, then the attachments"
    action = next(a for a in _declared(entry["connector"])["actions"] if a["id"] == entry["action_type"])
    assert action["gate_type"] == "approval", "LC-07: only a gated side effect of a declared action"
    table = _yaml("config", "autonomy.yaml")["actions"]
    assert table[entry["action_type"]] == action["risk_tier"], "the registry and the tier table agree"
    owner = evidence["policy"]["owner"] if evidence["policy"] else entry["authz"]["ref"]
    assert evidence["world_owner"] == owner, "the grant used is the world owner's"
    policy = pytest.importorskip("tilo_policy")
    assert policy.check_entry({**copy.deepcopy(evidence), "entry": entry, "transfer": None, "rule": None}) is None


def test_FR_CON_02_ADR35_L1_the_sent_marker_is_the_side_effect_marker_of_its_request():
    google = pytest.importorskip("tilo_connectors.adapters._google")
    request = next(r for r in _fixtures("execute_request") if r["entry"]["action_type"] == "create_draft")
    [sent] = [a for a in _fixtures("execute_answer") if a["outcome"] == "sent"]
    assert sent["result"]["marker"] == google.side_effect_marker(request["entry"]), "LC-08"


def test_FR_CON_02_ADR35_L1_error_codes_gain_three_and_keep_the_four(contracts_root):
    enum = load_json(contracts_root / "meeting_host_rpc.schema.json")["$defs"]["error"]["properties"]["error"]["enum"]
    assert set(enum) == {
        "unauthenticated",
        "forbidden",
        "invalid_request",
        "not_configured",
        "start_again",
        "not_granted",
        "wrong_account",
    }


def test_FR_CON_02_ADR35_L1_connector_parts_are_connection_events_of_any_connector_and_never_a_consent(
    contracts_root, registry
):
    defs = load_json(contracts_root / "meeting_host_rpc.schema.json")["$defs"]
    assert set(defs["connector_part"]["properties"]["type"]["enum"]) == {
        "connection.established",
        "connection.expired",
        "connection.rate_limited",
        "connection.revoked",
    }
    assert defs["connection_part"]["properties"]["connector"] == {"const": "meeting_host"}, "meeting-host parts stay"
    gmail = {"type": "connection.expired", "connector": "gmail", "user_id": "u_owner"}
    assert _errors(registry, "disconnect_answer", {"revoked_at_provider": False, "parts": [gmail]})
    assert not _errors(registry, "connection_disconnect_answer", {"revoked_at_provider": False, "parts": [gmail]})


GENERATED = [
    "MeetingHostRpc" + "".join(p.title() for p in m.split("_"))
    for m in (*MESSAGES, "connector_part", "execute_evidence", "execute_result")
]


@pytest.mark.parametrize("name", GENERATED)
def test_FR_CON_02_ADR35_L1_generated_types_exist(name):
    import tilo_contracts

    assert hasattr(tilo_contracts, name), f"tilo_contracts.{name} is missing: run `just contracts-gen`"
    ts = (ROOT / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    assert re.search(rf"\bexport (?:interface|type) {name}\b", ts), f"@tilo/contracts {name} is missing"


CALENDAR = "https://www.googleapis.com/auth/calendar.events.owned"


def test_FR_CON_02_ADR35_L1_google_calendar_declares_create_event_T1_and_create_event_with_guests_T3():
    decl = _declared("google_calendar")
    assert decl["scopes"] == {
        "read": ["https://www.googleapis.com/auth/calendar.readonly"],
        "write": [CALENDAR],
        "send": [CALENDAR],
    }
    assert decl["capabilities"] == ["read", "write", "send"]
    rows = {a["id"]: a for a in decl["actions"]}
    assert list(rows) == ["read_events", "create_event", "create_event_with_guests"]
    assert (rows["create_event"]["capability"], rows["create_event"]["risk_tier"]) == ("write", "T1")
    assert (rows["create_event"]["gate_type"], rows["create_event"]["irreversible"]) == ("approval", False)
    guests = rows["create_event_with_guests"]
    assert (guests["capability"], guests["risk_tier"], guests["gate_type"]) == ("send", "T3", "approval")
    assert guests["irreversible"] is True, "Google emails the guests (FR-CAL-04)"
    assert rows["read_events"]["gate_type"] == "none" and decl["limits"] == {"per_minute": 60, "batch_size": 2500}
    for other in (c for c in _yaml("config", "connectors.yaml") if c["id"] not in ("google_calendar", "meeting_host")):
        assert "calendar" not in yaml.safe_dump(other["scopes"]), f"{other['id']} gains no calendar scope"


def test_FR_CON_02_ADR35_L1_the_tier_table_lists_both_calendar_writes_and_a_person_decides_T3():
    table = _yaml("config", "autonomy.yaml")
    assert table["actions"]["create_event"] == "T1" and table["actions"]["create_event_with_guests"] == "T3"
    assert table["max_level"]["T3"] == "L1", "T3 runs at L1 only: a person decides"
