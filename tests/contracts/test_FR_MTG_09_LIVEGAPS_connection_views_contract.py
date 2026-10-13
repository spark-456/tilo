"""FR-MTG-09, LIVE-GAPS (BQ-LIVEGAPS-1), ADR-0032 addendum 1 (docs/adr/0032a-connection-views.md), ticket T1b:
`views_answer` and `connection_view` in contracts/meeting_host_rpc.schema.json 1.1.0. A person's connection views
cross from tilo-connectors to tilo-api as connector, state, scopes and connected_at only (HB-08), built from the
registry's oauth2 connectors and their declared scopes (HB-09). The request is the existing `user_request`."""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml
from _lib import errors_for, load_json

BASE = "https://contracts.tilo.example/meeting_host_rpc.schema.json"
FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "meeting_host_rpc.views_answer"
VIEW_KEYS = {"connector", "state", "scopes", "connected_at"}
GOOGLE = "https://www.googleapis.com/auth/"
AT = "2026-10-08T09:30:00.000Z"


def _errors(registry, doc, name="views_answer"):
    return errors_for({"$ref": f"{BASE}#/$defs/{name}"}, doc, registry)


def _valid():
    return [load_json(p) for p in sorted((FIXTURES / "valid").glob("*.json"))]


def _view(connector="gmail", scopes=None, state="connected", connected_at=AT):
    scopes = [f"{GOOGLE}gmail.readonly"] if scopes is None else scopes
    return {"connector": connector, "state": state, "scopes": scopes, "connected_at": connected_at}


@pytest.fixture(scope="module")
def declared(repo_root):
    """config/connectors.yaml: the oauth2 connectors in registry order, each with the union of its declared scopes."""
    entries = yaml.safe_load((repo_root / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    return {e["id"]: {s for scopes in e["scopes"].values() for s in scopes} for e in entries if e["auth"] == "oauth2"}


def test_FR_MTG_09_LIVEGAPS_views_are_an_additive_minor_of_the_host_rpc(contracts_root):
    schema = load_json(contracts_root / "meeting_host_rpc.schema.json")
    major, minor, _ = (int(x) for x in schema["x-version"].split("."))
    assert major == 1 and minor >= 1, "views_answer is additive: 1.1.0"
    defs = schema["$defs"]
    assert {"$ref": "#/$defs/views_answer"} in schema["anyOf"]
    assert set(defs["views_answer"]["properties"]) == set(defs["views_answer"]["required"]) == {"views"}
    assert set(defs["connection_view"]["properties"]) == set(defs["connection_view"]["required"]) == VIEW_KEYS
    assert defs["connection_view"]["properties"]["state"]["enum"] == ["connected", "expired"]
    assert set(defs["user_request"]["properties"]) == {"user_id"}, "HB-08: the views request is the user id only"


def test_FR_MTG_09_LIVEGAPS_valid_views_hold_HB_09_against_the_registry(declared):
    order = list(declared)
    for doc in _valid():
        ids = [view["connector"] for view in doc["views"]]
        assert len(ids) == len(set(ids)), "HB-09: each connector at most once"
        assert ids == [cid for cid in order if cid in ids], "HB-09: oauth2 connectors of the registry, in its order"
        for view in doc["views"]:
            assert view["scopes"] == sorted(view["scopes"]), "HB-09: scopes sorted"
            assert set(view["scopes"]) <= declared[view["connector"]], "HB-09: only scopes the registry declares"


def test_FR_MTG_09_LIVEGAPS_every_declared_connector_and_scope_fits_a_view(registry, declared):
    assert 0 < len(declared) <= 32, "every oauth2 connector fits in one answer"
    views = [_view(cid, sorted(scopes)) for cid, scopes in declared.items()]
    assert all(len(view["scopes"]) <= 16 for view in views)
    assert not _errors(registry, {"views": views}), "a scope config/connectors.yaml declares breaks the view's shape"


def test_FR_MTG_09_LIVEGAPS_views_scopes_and_scope_length_are_capped(registry):
    for count, ok in ((32, True), (33, False)):
        assert bool(_errors(registry, {"views": [_view()] * count})) is not ok, f"{count} views"
    many = [f"{GOOGLE}s{i:02d}" for i in range(17)]
    for count, ok in ((16, True), (17, False)):
        assert bool(_errors(registry, {"views": [_view(scopes=many[:count])]})) is not ok, f"{count} scopes"
    for length, ok in ((300, True), (301, False)):
        scope = GOOGLE + "a" * (length - len(GOOGLE))
        assert bool(_errors(registry, {"views": [_view(scopes=[scope])]})) is not ok, f"a scope of {length}"


def test_FR_MTG_09_LIVEGAPS_an_answer_at_its_caps_stays_under_256_KiB(registry):
    scopes = [f"{GOOGLE}{i:02d}" + "a" * (300 - len(GOOGLE) - 2) for i in range(16)]
    answer = {"views": [_view(f"c{i:02d}", scopes) for i in range(32)]}
    assert not _errors(registry, answer)
    assert len(json.dumps(answer).encode()) <= 256 * 1024, "tilo-api's client reads at most 256 KiB"


@pytest.mark.parametrize(
    "scope",
    [
        f"{GOOGLE}gmail.readonly?access_token=fake-value",
        f"{GOOGLE}gmail.readonly#fragment",
        f"{GOOGLE}gmail.readonly%3Faccess_token",
        "https://person@example.com/auth/gmail.readonly",
        "//person@example.com",
        "https:\\person@example.com",
        f" {GOOGLE}gmail.readonly",
        f"{GOOGLE}gmail.readonly\n",
        "openid email",
        "",
        f"{GOOGLE}‮gmail.readonly",
    ],
    ids=lambda s: repr(s)[:40],
)
def test_FR_MTG_09_LIVEGAPS_a_scope_outside_the_closed_shape_is_refused(registry, scope):
    assert _errors(registry, {"views": [_view(scopes=[scope])]})


def test_FR_MTG_09_LIVEGAPS_an_expired_view_carries_no_scope_and_no_connected_at(registry):
    assert not _errors(registry, {"views": [_view(state="expired", scopes=[], connected_at=None)]})
    assert _errors(registry, {"views": [_view(state="expired", connected_at=None)]}), "scopes on an expired grant"
    assert _errors(registry, {"views": [_view(state="expired", scopes=[])]}), "connected_at on an expired grant"
    assert not _errors(registry, {"views": [_view(connected_at=None)]}), "a grant from before HB-06 recorded it"


@pytest.mark.parametrize("name", ["MeetingHostRpcViewsAnswer", "MeetingHostRpcConnectionView"])
def test_FR_MTG_09_LIVEGAPS_generated_view_types_exist(repo_root, name):
    import tilo_contracts

    assert hasattr(tilo_contracts, name), f"tilo_contracts.{name} is missing: run `just contracts-gen`"
    ts = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    assert f"export interface {name} " in ts or f"export type {name} " in ts, f"@tilo/contracts {name} is missing"
