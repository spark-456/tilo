"""ADR-0052 proposal shape: one consent, exact configured scopes, honest per-connector outcomes."""

from __future__ import annotations

import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures" / "meeting_host_rpc"
GOOGLE = ("gmail", "google_calendar", "google_drive")


def _read(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_CX_GOOGLE_ONE_CONNECT_scope_set_is_exactly_the_registry_union():
    connectors = yaml.safe_load((ROOT / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    registry = {row["id"]: row for row in connectors}
    expected = {
        scope for connector_id in GOOGLE for values in registry[connector_id]["scopes"].values() for scope in values
    }
    schema = _read(ROOT / "contracts" / "meeting_host_rpc.schema.json")
    proposed = set(schema["$defs"]["google_person_scope"]["enum"])
    assert proposed == expected
    assert "meeting_host" not in schema["$defs"]["google_person_connector"]["enum"]


def test_CX_GOOGLE_ONE_CONNECT_partial_grant_keeps_only_fully_scoped_connectors_connected():
    start = _read(FIXTURES / "start_request" / "valid" / "google_connect.json")
    answer = _read(FIXTURES / "callback_answer" / "valid" / "google_partial_scopes.json")
    assert set(start["connectors"]) == set(GOOGLE)
    states = {item["connector"]: item for item in answer["connections"]}
    connectors = yaml.safe_load((ROOT / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    config = {row["id"]: row for row in connectors}
    for connector_id in GOOGLE:
        expected = {scope for values in config[connector_id]["scopes"].values() for scope in values}
        result = states[connector_id]
        assert set(result["requested_scopes"]) == expected
        assert set(result["requested_scopes"]) == (set(result["granted_scopes"]) | set(result["missing_scopes"]))
        assert result["state"] == ("connected" if not result["missing_scopes"] else "needs_setup")
    assert states["gmail"]["state"] == "needs_setup"
    assert not set(states["gmail"]["granted_scopes"]) & set(states["gmail"]["missing_scopes"])
    assert states["google_calendar"]["state"] == "connected"
    assert states["google_drive"]["state"] == "connected"
    established = {part["connector"] for part in answer["parts"]}
    assert established == {"google_calendar", "google_drive"}
