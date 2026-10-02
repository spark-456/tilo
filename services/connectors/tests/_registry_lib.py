"""Plain helpers for the FR-CON-01 connector registry tests (no production code).

Every config the tests load is written into pytest's tmp_path: config/ belongs to the CL-TRUST
lane and these tests never touch it. The shape of a config file is the one `config/teams.yaml`
already uses for a contract that is "one entry of" a config file: a top-level YAML list, each
item a `contracts/connector.schema.json` document (PRD 12.1: "Connectors are declared in
`config/connectors.yaml`"). An empty list is a valid, empty registry.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"

MOCK_ID = "mock_mail"

# PRD 9.5 world effects of connection events, expressed in the layout contract's island `state`
# vocabulary (contracts/layout.schema.json island.state: locked, requested, connected, failed).
# requested / consented: scaffold goes up, bridge ready to open      -> requested
# established / rate_limited / expiring: bridge open (cones, flicker) -> connected
# expired: "bridge planks drop"                                       -> failed ("access lost")
# revoked: "cloud cover returns"                                      -> locked ("cloud cover")
# No connection event yet: island under cloud cover                   -> locked
EVENT_TO_STATE = {
    "connection.requested": "requested",
    "connection.consented": "requested",
    "connection.established": "connected",
    "connection.rate_limited": "connected",
    "connection.expiring": "connected",
    "connection.expired": "failed",
    "connection.revoked": "locked",
}


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def valid_connector(name: str) -> dict:
    return load_json(CONTRACTS / "fixtures" / "connector" / "valid" / f"{name}.json")


def mock_entry(connector_id: str = MOCK_ID) -> dict:
    """A mock connector declared the way any connector is: a plain connector.schema.json entry.
    Two capabilities with scopes, one ungated read, one gated send (T2, irreversible)."""
    return {
        "id": connector_id,
        "name": "Mock Mail",
        "icon": "mail",
        "auth": "oauth2",
        "scopes": {
            "read": ["https://mock.example/auth/mail.read"],
            "send": ["https://mock.example/auth/mail.send"],
        },
        "capabilities": ["read", "send"],
        "actions": [
            {
                "id": "read_mock_mail",
                "capability": "read",
                "description": "Read a thread in the mock mailbox.",
                "risk_tier": "T1",
                "gate_type": "none",
                "irreversible": False,
            },
            {
                "id": "send_email",
                "capability": "send",
                "description": "Send a reply in an existing mock thread.",
                "risk_tier": "T2",
                "gate_type": "approval",
                "irreversible": True,
            },
        ],
        "limits": {"per_minute": 30, "batch_size": 10},
        "data_class": {"returns": ["personal"], "redact": ["body_signature"]},
    }


def write_config(directory: pathlib.Path, entries: Any, name: str = "connectors.yaml") -> pathlib.Path:
    """Write `entries` (normally a list of connector dicts) as YAML under `directory`."""
    path = directory / name
    path.write_text(yaml.safe_dump(copy.deepcopy(entries), sort_keys=False), encoding="utf-8")
    return path


def connection_event(event_type: str, connector: str, seq: int = 1) -> dict:
    """A recorded connection.* event: the real fixture for `event_type` with its connector and seq
    replaced. Only the fields of the event envelope (contracts/event.schema.json) are used."""
    event = load_json(CONTRACTS / "fixtures" / "events" / "valid" / f"{event_type}.json")
    event["data"]["connector"] = connector
    event["seq"] = seq
    return event
