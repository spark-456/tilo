"""ADR-0041 (BYOK-1; Proposed, inert): byok.schema.json, org_model_key.schema.json, model_call_rpc.schema.json,
meeting_host_rpc.schema.json 1.3.0 (`model_key_*`) and providers.schema.json 1.4.0 (`credential`).

Each fixture against its message; every object closed; a key-bearing field only on the two put bodies (BK-02, BK-04,
BK-22); the key alphabet (BQ-BYOK-2); BK-12, BK-13 and PL-06 across documents; `trace.payer` is not applied
(BQ-BYOKC-3). The generated pydantic models do not enforce if/then/else, so these tests validate the JSON Schema."""

from __future__ import annotations

import json
import pathlib
import re

import pytest
from _lib import errors_for, load_json

HOST = "https://contracts.tilo.example/"
FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
MESSAGES = {
    "org_model_key": (
        "reference audit_entry put_request put_answer patch_request member_view owner_view remove_answer error"
    ).split(),
    "model_call_rpc": "generate_request generate_answer error".split(),
    "meeting_host_rpc": (
        "model_key_put_request model_key_put_answer model_key_remove_request model_key_remove_answer "
        "model_key_status_request model_key_status_answer"
    ).split(),
}
PUT_BODIES = {("org_model_key", "put_request"), ("meeting_host_rpc", "model_key_put_request")}
KEYISH = set(
    "key api_key secret secret_name credential authorization password bearer token lease key_length key_hash "
    "key_sha256 last_four base_url url host model".split()
)
CASES = [
    pytest.param(schema, name, kind, path, id=f"{schema}.{name}/{kind}/{path.stem}")
    for schema, names in MESSAGES.items()
    for name in names
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / f"{schema}.{name}" / kind).glob("*.json"))
]
CASES += [
    pytest.param("byok", None, kind, path, id=f"byok/{kind}/{path.stem}")
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / "byok" / kind).glob("*.json"))
] + [
    pytest.param("providers", None, kind, path, id=f"providers/{kind}/{path.stem}")
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / "providers" / kind).glob("*.json"))
    if path.stem.startswith(("credential_", "org_profile_"))
]
RULE = {"bk12": "BK-12", "bk13": "BK-13", "pl06": "PL-06"}
CROSSREF = [
    pytest.param(kind, path, id=f"{kind}/{path.stem}")
    for kind in ("valid", "invalid")
    for path in sorted((FIXTURES / "byok" / "crossref" / kind).glob("*.json"))
]


def _ref(schema, name=None):
    return {"$ref": f"{HOST}{schema}.schema.json" + (f"#/$defs/{name}" if name else "")}


def _schema(root, name):
    return load_json(root / f"{name}.schema.json")


@pytest.mark.parametrize(("schema", "name", "kind", "path"), CASES)
def test_ADR_0041_fixture_matches_its_message_schema(registry, schema, name, kind, path):
    doc, found = load_json(path), errors_for(_ref(schema, name), load_json(path), registry)
    assert bool(found) is (kind == "invalid"), f"{path.name}: {[e.message for e in found][:2]}"
    if kind == "valid":
        assert not errors_for(_ref(schema), doc, registry), f"{path.name} must also match the root of {schema}"


def test_ADR_0041_BK_12_versions_and_roots(contracts_root):
    for name, title in (("byok", "ByokConfig"), ("org_model_key", "OrgModelKey"), ("model_call_rpc", "ModelCallRpc")):
        schema = _schema(contracts_root, name)
        assert schema["title"] == title and schema["$id"] == f"{HOST}{name}.schema.json"
        assert re.fullmatch(r"1\.\d+\.\d+", schema["x-version"])
    assert tuple(map(int, _schema(contracts_root, "providers")["x-version"].split("."))) >= (1, 4, 0)
    assert tuple(map(int, _schema(contracts_root, "meeting_host_rpc")["x-version"].split("."))) >= (1, 3, 0)
    assert "key_refused" in _schema(contracts_root, "meeting_host_rpc")["$defs"]["error"]["properties"]["error"]["enum"]


def test_ADR_0041_BK_02_BK_04_every_object_is_closed_and_only_the_put_bodies_carry_a_key(contracts_root):
    for schema, names in MESSAGES.items():
        defs = _schema(contracts_root, schema)["$defs"]
        for name in names:
            assert defs[name].get("additionalProperties") is False, f"{schema}.{name} must be closed"
            for kind in ("valid", "invalid"):
                assert list((FIXTURES / f"{schema}.{name}" / kind).glob("*.json")), f"{schema}.{name} has no {kind}"
            carries = "key" in defs[name]["properties"]
            assert carries is ((schema, name) in PUT_BODIES), f"{schema}.{name}: only a put body has a key"
            assert bool(defs[name].get("x-no-store")) is carries, f"{schema}.{name}: put bodies are no-store"
    for schema in ("byok", "org_model_key", "model_call_rpc"):
        for name, node in _schema(contracts_root, schema)["$defs"].items():
            if node.get("type") == "object" and (schema, name) not in PUT_BODIES:
                assert not KEYISH & set(node.get("properties", {})), f"{schema}.{name} has a key-bearing field"


def test_ADR_0041_BK_21_the_request_has_no_media_part_and_there_is_no_lease_def(contracts_root):
    request = _schema(contracts_root, "model_call_rpc")["$defs"]["request"]
    assert set(request["properties"]) == set(
        "prompt system max_output_tokens tools json_mode response_schema thinking_level".split()
    )
    for schema in ("model_call_rpc", "meeting_host_rpc", "org_model_key"):
        assert not [n for n in _schema(contracts_root, schema)["$defs"] if "lease" in n.split("_")], schema


@pytest.mark.parametrize(
    ("value", "ok"),
    [("a" * 8, True), ("A-_.~+/=" * 64, True), ("fake-model-key_0123456789.example", True)]
    + [("a" * 7, False), ("a" * 513, False), ("", False), ("a b" * 4, False), ("a" * 8 + "\n", False)]
    + [("a" * 7 + "é", False), ('{"k": "v"}' * 2, False), ("a" * 7 + '"', False), ("a" * 7 + ",", False)],
    ids=lambda v: repr(v)[:24],
)
def test_ADR_0041_BQ_BYOK_2_key_alphabet_refuses_json_blobs_spaces_and_a_newline(registry, value, ok):
    put = load_json(FIXTURES / "org_model_key.put_request" / "valid" / "minimal.json")
    rpc = load_json(FIXTURES / "meeting_host_rpc.model_key_put_request" / "valid" / "typical.json")
    for schema, name, doc in (
        ("org_model_key", "put_request", put),
        ("meeting_host_rpc", "model_key_put_request", rpc),
    ):
        assert (not errors_for(_ref(schema, name), {**doc, "key": value}, registry)) is ok


def test_ADR_0041_BQ_BYOK_RECON_1_not_configured_is_in_the_owner_view_enum_only(contracts_root):
    schema = _schema(contracts_root, "org_model_key")
    defs, four = schema["$defs"], ["invalid_key", "quota", "rate_limited", "unreachable"]
    assert tuple(map(int, schema["x-version"].split("."))) >= (1, 1, 0)
    assert defs["last_error"]["enum"] == four, "the stored code is the provider's refusal only (BK-17)"
    assert defs["owner_last_error"]["enum"] == [*four, "not_configured"]

    def nullable(name):
        return {"anyOf": [{"$ref": f"#/$defs/{name}"}, {"type": "null"}]}

    assert defs["reference"]["properties"]["last_error"] == nullable("last_error")
    assert defs["owner_view"]["properties"]["last_error"] == nullable("owner_last_error")
    users = [n for n, node in defs.items() if "owner_last_error" in json.dumps(node) and n != "owner_last_error"]
    assert users == ["owner_view"], "only the owner's answer may say not_configured"
    assert set(defs["member_view"]["properties"]) == {"active", "label"}


@pytest.mark.parametrize(
    ("state", "active", "last_error", "ok"),
    [("active", False, "not_configured", True), ("paused", False, "not_configured", True)]
    + [("unverified", False, "not_configured", True), ("invalid", False, "not_configured", True)]
    + [("active", True, "not_configured", False), ("paused", True, "not_configured", False)]
    + [("active", True, None, True), ("active", True, "quota", True), ("invalid", False, "invalid_key", True)]
    + [("active", False, None, False), ("active", False, "quota", False), ("active", False, "key_paused", False)],
    ids=lambda v: str(v),
)
def test_ADR_0041_BQ_BYOK_RECON_1_a_key_whose_bundle_left_the_config_is_never_said_to_be_active(
    registry, state, active, last_error, ok
):
    doc = load_json(FIXTURES / "org_model_key.owner_view" / "valid" / "active.json")
    doc = {**doc, "state": state, "active": active, "last_error": last_error}
    assert (not errors_for(_ref("org_model_key", "owner_view"), doc, registry)) is ok


def test_ADR_0041_BQ_BYOK_RECON_1_the_stored_reference_refuses_not_configured(registry):
    held = load_json(FIXTURES / "org_model_key.reference" / "valid" / "first_set.json")
    assert not errors_for(_ref("org_model_key", "reference"), {**held, "last_error": "quota"}, registry)
    assert errors_for(_ref("org_model_key", "reference"), {**held, "last_error": "not_configured"}, registry)


@pytest.mark.parametrize(("field", "limit"), [("prompt", 400000), ("system", 400000)])
def test_ADR_0041_model_call_request_text_is_bounded_at_four_chars_per_role_cap_token(registry, field, limit):
    doc = load_json(FIXTURES / "model_call_rpc.generate_request" / "valid" / "minimal.json")
    for size, ok in ((limit, True), (limit + 1, False)):
        request = {**doc["request"], field: "x" * size}
        assert (not errors_for(_ref("model_call_rpc", "generate_request"), {**doc, "request": request}, registry)) is ok


def _problems(case):
    """The BK-12, BK-13 and PL-06 cross-document check (the loader must reach the same verdicts)."""
    models, prices = case["providers"]["models"], case["providers"]["prices"]
    profiles, roles, out = models["profiles"], models["roles"], []
    named = {p for r in roles.values() for p in (r.get("primary"), r.get("fallback"), *r.get("cascade", [])) if p}
    out += [f"BK-12 {p}" for p in sorted(named) if profiles.get(p, {}).get("credential") == "org"]
    for bundle_id, bundle in case["byok"]["bundles"].items():
        for role, pair in bundle["roles"].items():
            out += [f"BK-13 {bundle_id}.{role}"] if role not in roles else []
            for profile_id in pair.values():
                if profiles.get(profile_id, {}).get("credential") != "org":
                    out.append(f"BK-12 {bundle_id}.{profile_id}")
                    continue
                price = prices["profiles"].get(profile_id) or {}
                if prices["status"] != "set" or price.get("input") is None or price.get("output") is None:
                    out.append(f"PL-06 {bundle_id}.{profile_id}")
    return out


@pytest.mark.parametrize(("kind", "path"), CROSSREF)
def test_ADR_0041_BK_12_BK_13_PL_06_bundles_against_the_model_config(registry, kind, path):
    case = load_json(path)
    assert not errors_for(_ref("byok"), case["byok"], registry), "the byok half must be valid alone"
    assert not errors_for(_ref("providers"), case["providers"], registry), "the providers half must be valid alone"
    found = {p.split(" ")[0] for p in _problems(case)}
    expected = set() if kind == "valid" else {RULE[path.stem.split("_")[0]]}
    assert found == expected, f"{path.name} must break exactly {sorted(expected)}, got {sorted(found)}"


def test_ADR_0041_BQ_BYOKC_3_trace_payer_is_not_applied_until_the_user_says_yes(contracts_root):
    trace = _schema(contracts_root, "event")["$defs"]["trace"]["properties"]
    assert "payer" not in trace, "trace.payer needs the user's yes (ADR-0041 decision 12): see byok.rules.md"
    rules = (contracts_root / "byok.rules.md").read_text(encoding="utf-8")
    assert all(f"| BK-{n:02d} |" in rules for n in range(1, 23)) and '"enum": ["tilo", "org_key"]' in rules


@pytest.mark.parametrize(
    "name",
    "ByokConfig OrgModelKey OrgModelKeyPutRequest OrgModelKeyOwnerView ModelCallRpcGenerateRequest "
    "MeetingHostRpcModelKeyPutRequest".split(),
)
def test_ADR_0041_generated_types_exist(repo_root, name):
    import tilo_contracts

    ts = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    assert hasattr(tilo_contracts, name), f"tilo_contracts.{name} is missing: run `just contracts-gen`"
    assert re.search(rf"\bexport (?:interface|type) {name}\b", ts), f"@tilo/contracts {name} is missing"
