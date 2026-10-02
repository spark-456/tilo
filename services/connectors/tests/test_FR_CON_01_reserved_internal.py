"""FR-CON-01 (ADR-0002 decision 14, issue #137): `internal` is the reserved connector id for actions
that go through no connector, and `grant_budget` is such an action. The registry refuses a connector
declared with either, and the Outbox never binds `internal`.
"""

from __future__ import annotations

import pytest
import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from _registry_lib import MOCK_ID, mock_entry, write_config
from tilo_connectors.fakes import FakeGmail
from tilo_connectors.registry import ConnectorConfigError, load_registry


def test_FR_CON_01_registry_refuses_the_reserved_internal_id(tmp_path):
    path = write_config(tmp_path, [mock_entry(), mock_entry("internal")])

    with pytest.raises(ConnectorConfigError, match="'internal'.*reserved"):
        load_registry(path)


def test_FR_CON_01_registry_refuses_a_grant_budget_connector_action(tmp_path):
    entry = mock_entry()
    entry["actions"].append(
        {
            "id": "grant_budget",
            "capability": "read",
            "description": "Not a connector action.",
            "risk_tier": "T1",
            "gate_type": "none",
            "irreversible": False,
        }
    )
    path = write_config(tmp_path, [entry])

    with pytest.raises(ConnectorConfigError, match=f"{MOCK_ID}.*grant_budget"):
        load_registry(path)


def test_FR_CON_01_registry_refuses_reserved_ids_with_a_trailing_newline(tmp_path):
    # `$` in the schema patterns matches before a final "\n", so these pass the schema itself.
    entry = mock_entry()
    entry["actions"][0]["id"] = "grant_budget\n"
    for entries in ([mock_entry("internal\n")], [entry]):
        with pytest.raises(ConnectorConfigError, match="whitespace"):
            load_registry(write_config(tmp_path, entries))


def test_FR_CON_01_outbox_refuses_to_bind_internal_with_a_trailing_newline():
    with pytest.raises(ValueError, match="reserved"):
        tilo_connectors.Outbox(
            tilo_connectors.InMemoryOutboxStore(),
            {"internal\n": FakeGmail()},
            [].append,
            ManualClock("2026-09-29T09:00:00.000Z"),
        )


def test_FR_CON_01_a_normal_config_still_loads(tmp_path):
    registry = load_registry(write_config(tmp_path, [mock_entry(), mock_entry("mock_two")]))

    assert registry.ids() == (MOCK_ID, "mock_two")
    assert "internal" not in registry


def test_FR_CON_01_outbox_refuses_to_bind_internal():
    with pytest.raises(ValueError, match="reserved"):
        tilo_connectors.Outbox(
            tilo_connectors.InMemoryOutboxStore(),
            {"gmail": FakeGmail(), "internal": FakeGmail()},
            [].append,
            ManualClock("2026-09-29T09:00:00.000Z"),
        )


def test_FR_CON_01_outbox_never_dispatches_to_internal_even_if_the_map_is_edited_later(gate_case_factory):
    case = gate_case_factory(undo_window_s=0)
    case["entry"]["connector"] = "internal"
    connectors: dict = {}
    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), connectors, [].append, ManualClock("2026-09-29T09:00:00.000Z")
    )
    outbox.enqueue(case["entry"], evidence_from_case(case))
    sneaky = FakeGmail()
    connectors["internal"] = sneaky  # bound after construction

    settled = outbox.dispatch_due()

    assert sneaky.sent == []
    assert [e["state"] for e in settled] == ["failed"]
