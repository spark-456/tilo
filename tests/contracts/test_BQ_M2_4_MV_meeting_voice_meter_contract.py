"""BQ-M2-4, BQ-M2-5, ADR-0042 T1: contracts/meeting_voice_meter.schema.json. Each fixture against its message;
every object closed; no identity, amount or time field (MV-03, MV-04); the usage bound of 16384 is a 422 (MV-15);
the claim and key shapes (MV-16); reason and usage appear exactly when they must; the rules file (MV-01..MV-17)."""

from __future__ import annotations

import copy
import pathlib
import re

import pytest
from _lib import errors_for, load_json

BASE = "https://contracts.tilo.example/meeting_voice_meter.schema.json"
FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
MESSAGES = ("reserve_request", "reserve_answer", "close_request", "close_answer", "error")
REQUESTS = ("reserve_request", "close_request")
NAMES = {
    "meeting_id",
    "claim",
    "key",
    "outcome",
    "usage",
    "decision",
    "reason",
    "error",
    "prompt_token_count",
    "response_token_count",
    "total_token_count",
}
COUNTS = ("prompt_token_count", "response_token_count", "total_token_count")
STATUS = {
    "unauthenticated": 401,
    "forbidden": 403,
    "not_attending": 409,
    "no_hold": 409,
    "key_used": 409,
    "invalid_request": 422,
    "not_configured": 503,
}
CASES = [
    pytest.param(name, kind, path, id=f"{name}/{kind}/{path.stem}")
    for name in MESSAGES
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / f"meeting_voice_meter.{name}" / kind).glob("*.json"))
]


def _errors(registry, name, doc):
    return errors_for({"$ref": f"{BASE}#/$defs/{name}"}, doc, registry)


def _valid(name):
    return [load_json(p) for p in sorted((FIXTURES / f"meeting_voice_meter.{name}" / "valid").glob("*.json"))]


def _close(**usage):
    return {"meeting_id": "mt_weekly_sync", "claim": "c" * 32, "key": "k" * 16, "outcome": "settled", "usage": usage}


def test_BQ_M2_4_MV_03_meeting_voice_meter_is_a_versioned_2020_12_contract_with_fixtures(contracts_root):
    schema = load_json(contracts_root / "meeting_voice_meter.schema.json")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema" and schema["$id"] == BASE
    assert schema["title"] == "MeetingVoiceMeter" and re.fullmatch(r"1\.\d+\.\d+", schema["x-version"])
    assert {r["$ref"] for r in schema["anyOf"]} == {f"#/$defs/{m}" for m in MESSAGES}
    assert all(_valid(m) and list((FIXTURES / f"meeting_voice_meter.{m}" / "invalid").glob("*.json")) for m in MESSAGES)


@pytest.mark.parametrize(("name", "kind", "path"), CASES)
def test_BQ_M2_4_MV_03_fixture_matches_its_message_schema(registry, name, kind, path):
    doc, found = load_json(path), _errors(registry, name, load_json(path))
    if kind == "valid":
        assert not found, f"{path.name}: {[e.message for e in found][:3]}"
        assert not errors_for({"$ref": BASE}, doc, registry), f"{path.name} must also match the root"
    else:
        assert found, f"{path.name} validates but its name says which rule it breaks"


def test_BQ_M2_5_MV_03_every_object_is_closed_and_names_only_what_the_bot_holds(contracts_root):
    defs = load_json(contracts_root / "meeting_voice_meter.schema.json")["$defs"]
    names = set()
    for name, node in defs.items():
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, f"$defs/{name} must be closed"
            names |= set(node["properties"])
    assert names == NAMES, "no user, org, run, hold, amount, cap, price or time field (MV-03, MV-04)"


@pytest.mark.parametrize("name", MESSAGES)
@pytest.mark.parametrize(
    "extra",
    ["user_id", "org_id", "run_id", "hold_id", "hold", "unit_id", "amount_minor", "price", "cap", "expires_at", "at"],
)
def test_BQ_M2_5_MV_03_a_smuggled_identity_amount_or_time_field_is_refused(registry, name, extra):
    for doc in _valid(name):
        assert _errors(registry, name, {**doc, extra: "u_owner"}), f"{name} accepts {extra!r}"
        if "usage" in doc:
            assert _errors(registry, name, {**doc, "usage": {**doc["usage"], extra: 1}}), f"usage accepts {extra!r}"


@pytest.mark.parametrize("field", COUNTS)
@pytest.mark.parametrize(
    ("value", "ok"),
    [(0, True), (1, True), (2048, True), (16384, True), (16385, False), (100000000, False)]
    + [(-1, False), (1.5, False), ("7", False), (True, False), (None, False)],
    ids=repr,
)
def test_BQ_M2_4_MV_15_usage_bound_16384_is_refused_before_any_code_runs(registry, field, value, ok):
    assert bool(_errors(registry, "close_request", _close(**{field: value}))) is not ok


def test_BQ_M2_4_MV_15_the_refusal_of_a_count_above_16384_is_a_422_invalid_request(contracts_root):
    rules = (contracts_root / "meeting_voice_meter.rules.md").read_text(encoding="utf-8")
    assert re.search(r"\| 422 \| `error` `invalid_request` \|[^\n]*`usage` above 16384", rules)
    assert re.search(
        r"usage count above 16384",
        load_json(contracts_root / "meeting_voice_meter.schema.json")["$defs"]["error"]["description"],
    )


@pytest.mark.parametrize("name", REQUESTS)
@pytest.mark.parametrize(
    ("field", "good", "bad"),
    [
        ("claim", ["a" * 32, "A-_" * 21 + "z", "9" * 64], ["a" * 31, "a" * 65, "", "a" * 31 + " ", "a" * 32 + "\n"]),
        ("claim", [], ["a" * 31 + "/", "a" * 31 + "+", "a" * 31 + ".", "a" * 31 + "é", "a" * 31 + "="]),
        ("key", ["k" * 16, "K-_" * 21 + "z", "9" * 64], ["k" * 15, "k" * 65, "", "k" * 15 + " ", "k" * 16 + "\n"]),
        ("key", [], ["k" * 15 + "/", "k" * 15 + "+", "k" * 15 + ".", "k" * 15 + "é"]),
    ],
)
def test_BQ_M2_4_MV_16_claim_and_key_are_url_safe_tokens_of_a_fixed_length(registry, name, field, good, bad):
    base = _valid(name)[0]
    for value in good:
        assert not _errors(registry, name, {**base, field: value}), f"{field} {value!r} must pass"
    for value in bad:
        assert _errors(registry, name, {**base, field: value}), f"{field} {value!r} must fail"


@pytest.mark.parametrize("name", REQUESTS)
@pytest.mark.parametrize("field", ["meeting_id", "claim", "key"])
def test_BQ_M2_4_MV_16_a_request_without_its_claim_meeting_or_key_is_refused(registry, name, field):
    base = _valid(name)[0]
    without = {k: v for k, v in base.items() if k != field}
    assert _errors(registry, name, without), f"{name} without {field}"
    assert _errors(registry, name, {**base, field: None}), f"{name} with a null {field}"


@pytest.mark.parametrize("name", REQUESTS)
def test_BQ_M2_4_MV_03_meeting_id_is_a_meeting_id(registry, name):
    assert _errors(registry, name, {**_valid(name)[0], "meeting_id": "weekly_sync"}), "needs the mt_ prefix"


def test_BQ_M2_4_MV_07_a_reply_has_a_reason_exactly_when_the_decision_is_replay(registry):
    reasons = ("capped", "replay_only", "unavailable", "hold_open", "meeting_limit")
    for reason in reasons:
        assert not _errors(registry, "reserve_answer", {"decision": "replay", "reason": reason})
        assert _errors(registry, "reserve_answer", {"decision": "live", "reason": reason}), "live has no reason"
    assert not _errors(registry, "reserve_answer", {"decision": "live"})
    for bad in ({"decision": "replay"}, {"decision": "replay", "reason": None}, {"reason": "capped"}):
        assert _errors(registry, "reserve_answer", bad), bad


def test_BQ_M2_4_MV_05_a_close_has_usage_exactly_when_the_outcome_is_settled(registry):
    by_outcome = {doc["outcome"]: copy.deepcopy(doc) for doc in _valid("close_request")}
    settled, released = by_outcome["settled"], by_outcome["released"]
    assert not _errors(registry, "close_request", settled) and not _errors(registry, "close_request", released)
    assert _errors(registry, "close_request", {k: v for k, v in settled.items() if k != "usage"})
    assert _errors(registry, "close_request", {**released, "usage": {}}), "released carries no usage, not even {}"
    assert not _errors(registry, "close_request", {**settled, "usage": {}}), "settled with no counts is valid"


def test_BQ_M2_5_MV_01_the_error_codes_are_a_closed_set_with_their_status(contracts_root):
    schema = load_json(contracts_root / "meeting_voice_meter.schema.json")["$defs"]["error"]
    assert set(schema["properties"]["error"]["enum"]) == set(STATUS)
    rules = (contracts_root / "meeting_voice_meter.rules.md").read_text(encoding="utf-8")
    for code, status in STATUS.items():
        assert f"{code} ({status}" in schema["description"], f"{code} must name its status {status}"
        assert re.search(rf"\| {status} \| `error` [^|]*`{code}`", rules), f"rules table: {status} {code}"


def test_BQ_M2_5_MV_16_the_rules_file_carries_every_rule_and_the_attend_header(contracts_root):
    rules = (contracts_root / "meeting_voice_meter.rules.md").read_text(encoding="utf-8")
    for number in range(1, 18):
        assert f"| MV-{number:02d} |" in rules, f"MV-{number:02d} is missing"
    schema = load_json(contracts_root / "meeting_voice_meter.schema.json")
    assert "X-Tilo-Meeting-Claim" in rules and "X-Tilo-Meeting-Claim" in schema["$defs"]["claim"]["description"]


def test_BQ_M2_4_MV_03_meeting_join_stays_the_owners_answer_and_is_not_the_bots_contract(contracts_root):
    join = load_json(contracts_root / "meeting_join.schema.json")
    assert set(join["properties"]) == {"join_url", "expires_at"}, "no bot-only field on MeetingJoin (ADR-0042 d1)"
    assert "meeting_join" not in (contracts_root / "meeting_voice_meter.schema.json").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name", ["MeetingVoiceMeter", *("MeetingVoiceMeter" + "".join(p.title() for p in m.split("_")) for m in MESSAGES)]
)
def test_BQ_M2_4_generated_types_exist(repo_root, name):
    import tilo_contracts

    assert hasattr(tilo_contracts, name), f"tilo_contracts.{name} is missing: run `just contracts-gen`"
    ts = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    assert re.search(rf"\bexport (?:interface|type) {name}\b", ts), f"@tilo/contracts {name} is missing"
