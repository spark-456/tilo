"""Shared fixtures, JSON Schema validation helpers and plain data factories for
services/connectors acceptance tests (ticket ST-2: FR-AGT-11, FR-CHN-13, SEC-03, and OB-02,
OB-03, OB-05, PI-12, PI-14, PI-16, PI-17 of docs/security/p4-policy-invariants.md).

No production code lives here (root CLAUDE.md test-writer rule): every helper below either
loads a contracts/ file unchanged, builds a jsonschema validator from those files, or returns a
literal dict/object shaped like the contract or test double it names. `tilo_connectors` itself
(services/connectors/src) does not exist yet; importing it is what makes these tests fail for
the right reason until a builder ships it (see API.md in this directory).

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here — the same plain-module-import pattern
packages/policy/tests/conftest.py and tests/contracts/_lib.py use.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import jsonschema
import pytest
from _connectors_lib import (  # noqa: F401
    OWNER,
    RUN,
    WORLD,
    ManualClock,
    add_seconds,
    deep_copy,
    evidence_from_case,
    format_ts,
    parse_ts,
)
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

# The one file every SIDE_EFFECT_METHOD_NAMES call must live in (see API.md "SEC-03 static
# check, resolved"). Not created by this ticket (no production code); the constant exists so
# tests can name it before the builder creates the file.
OUTBOX_MODULE_PATH = REPO_ROOT / "services" / "connectors" / "src" / "tilo_connectors" / "outbox.py"


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def outbox_module_path() -> pathlib.Path:
    return OUTBOX_MODULE_PATH


def contracts_dir(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "contracts"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def list_fixtures(repo_root: pathlib.Path, relative: str) -> list[pathlib.Path]:
    """Every *.json directly under contracts/fixtures/<relative>/."""
    d = contracts_dir(repo_root) / "fixtures" / relative
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


@pytest.fixture()
def crossref_valid_cases(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/crossref/valid")]


@pytest.fixture()
def crossref_invalid_cases(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/crossref/invalid")]


@pytest.fixture()
def outbox_valid_fixtures(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/valid")]


@pytest.fixture()
def outbox_invalid_fixtures(repo_root: pathlib.Path) -> list[tuple[str, dict]]:
    return [(p.name, load_json(p)) for p in list_fixtures(repo_root, "outbox/invalid")]


# ---------------------------------------------------------------------------
# JSON Schema validation (contracts/outbox.schema.json, contracts/events/data/data.transfer.schema.json)
# Mirrors tests/contracts/_lib.py's registry-building approach so cross-file $refs
# (common.schema.json, policy.schema.json) resolve the same way the contracts-check gate does.


def build_registry(repo_root: pathlib.Path) -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(contracts_dir(repo_root).glob("**/*.schema.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@pytest.fixture(scope="session")
def schema_registry(repo_root: pathlib.Path) -> Registry:
    return build_registry(repo_root)


def _validator_for(schema: dict[str, Any], registry: Registry) -> jsonschema.protocols.Validator:
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return cls(schema, registry=registry)


@pytest.fixture()
def outbox_schema_errors(repo_root: pathlib.Path, schema_registry: Registry):
    schema = load_json(contracts_dir(repo_root) / "outbox.schema.json")
    validator = _validator_for(schema, schema_registry)

    def _errors(instance: dict) -> list[str]:
        return [e.message for e in validator.iter_errors(instance)]

    return _errors


@pytest.fixture()
def data_transfer_schema_errors(repo_root: pathlib.Path, schema_registry: Registry):
    schema = load_json(contracts_dir(repo_root) / "events" / "data" / "data.transfer.schema.json")
    validator = _validator_for(schema, schema_registry)

    def _errors(instance: dict) -> list[str]:
        return [e.message for e in validator.iter_errors(instance)]

    return _errors


def gate_case(
    *,
    outbox_id: str = "01JB5VQ0000000000000009100",
    idempotency_key: str = "r_village_basic_1:U2:send_email:100",
    connector: str = "gmail",
    action_type: str = "send_email",
    recipients: tuple[str, ...] = ("riya@example.com",),
    destination: str = "thread-supplier-1",
    item: dict | None = None,
    risk_tier: str = "T2",
    undo_window_s: int = 0,
    created_at: str = "2026-09-29T09:32:09.500Z",
    approver: str = OWNER,
    world_id: str = WORLD,
    run_id: str = RUN,
) -> dict:
    """A gate-authorised case (PI-02, mirrors oc/valid/gate_reply_sent_in_village_basic.json)
    with a state freshly computed from undo_window_s/created_at (OB-02), ready to enqueue and
    then dispatch in a test — the fixture file itself is post-send ("sent"), which is not
    useful for tests that want to dispatch the entry themselves."""
    item = item if item is not None else {"artifact_id": "art_reply_draft", "version": 1}
    scheduled_at = add_seconds(created_at, undo_window_s)
    state = "queued" if undo_window_s == 0 else "scheduled"
    entry = {
        "id": outbox_id,
        "idempotency_key": idempotency_key,
        "world_id": world_id,
        "run_id": run_id,
        "action_type": action_type,
        "connector": connector,
        "recipients": list(recipients),
        "attachments": [],
        "item": item,
        "destination": destination,
        "modifiers": [],
        "risk_tier": risk_tier,
        "authz": {"by": "person", "ref": approver, "at": created_at},
        "undo_window_s": undo_window_s,
        "scheduled_at": scheduled_at,
        "state": state,
        "created_at": created_at,
    }
    reserved_by = {
        "type": "approval.requested",
        "authz": None,
        "data": {
            "gate_id": "G1",
            "card_id": "01JB5VQ0000000000000009099",
            "outbox_id": outbox_id,
            "action_type": action_type,
            "risk_tier": risk_tier,
            "irreversible": True,
            "item": item,
            "approver": None,
            "team_lead": None,
        },
    }
    authorised_by = {
        "type": "approval.resolved",
        "authz": {"by": "person", "ref": approver, "at": created_at},
        "data": {
            "gate_id": "G1",
            "card_id": "01JB5VQ0000000000000009099",
            "outbox_id": outbox_id,
            "option": "approve",
            "channel": "web",
            "pin_verified": False,
        },
    }
    return {
        "rule": None,
        "note": "test factory: gate-authorised, not yet dispatched",
        "entry": entry,
        "reserved_by": reserved_by,
        "authorised_by": authorised_by,
        "policy": None,
        "team_lead": None,
        "world_owner": OWNER,
        "instruction": None,
        "earlier_applied": None,
        "transfer": None,
    }


@pytest.fixture(scope="session")
def gate_case_factory():
    return gate_case


def l2_undo_window_case(repo_root: pathlib.Path, **overrides: Any) -> dict:
    """Loads contracts/fixtures/outbox/crossref/valid/policy_reply_waiting_out_undo_window.json
    (the ticket's own named fixture for the L2 path) and applies `overrides` to a deep copy, so
    a test can mint a second, independent entry from the same authorised shape (new id,
    idempotency_key, instruction id) without colliding with the first in the same store."""
    path = (
        contracts_dir(repo_root)
        / "fixtures"
        / "outbox"
        / "crossref"
        / "valid"
        / "policy_reply_waiting_out_undo_window.json"
    )
    case = deep_copy(load_json(path))
    new_id = overrides.pop("outbox_id", None)
    new_key = overrides.pop("idempotency_key", None)
    new_instruction_id = overrides.pop("instruction_id", None)
    if new_id is not None:
        case["entry"]["id"] = new_id
        case["authorised_by"]["data"]["outbox_id"] = new_id
    if new_key is not None:
        case["entry"]["idempotency_key"] = new_key
    if new_instruction_id is not None:
        case["instruction"]["id"] = new_instruction_id
        case["authorised_by"]["data"]["instruction_id"] = new_instruction_id
    assert not overrides, f"unknown overrides: {sorted(overrides)}"
    return case


@pytest.fixture()
def l2_undo_window_case_factory(repo_root: pathlib.Path):
    def _factory(**overrides: Any) -> dict:
        return l2_undo_window_case(repo_root, **overrides)

    return _factory
