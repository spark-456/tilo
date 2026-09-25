"""OB-05 (contracts/outbox.rules.md, PI-14): Outbox.enqueue validates `entry` against
contracts/outbox.schema.json before anything else. Parametrized over every fixture under
contracts/fixtures/outbox/{valid,invalid}/ (one invalid file per schema rule) so a new fixture
is covered automatically, the same pattern the crossref tests use.
"""

from __future__ import annotations

import pytest
import tilo_connectors
from _connectors_lib import ManualClock
from tilo_connectors.fakes import FakeGmail


def make_outbox(emitted: list[dict]):
    store = tilo_connectors.InMemoryOutboxStore()
    return tilo_connectors.Outbox(
        store, {"gmail": FakeGmail()}, emitted.append, ManualClock("2026-09-29T09:00:00.000Z")
    )


def test_OB_05_every_valid_outbox_fixture_is_present(outbox_valid_fixtures):
    assert outbox_valid_fixtures, "contracts/fixtures/outbox/valid/ must hold at least one fixture"


def test_OB_05_every_invalid_outbox_fixture_is_present(outbox_invalid_fixtures):
    assert outbox_invalid_fixtures, "contracts/fixtures/outbox/invalid/ must hold at least one fixture"


def test_OB_05_every_valid_outbox_fixture_passes_schema(outbox_valid_fixtures, outbox_schema_errors):
    for name, entry in outbox_valid_fixtures:
        assert outbox_schema_errors(entry) == [], name


def test_OB_05_every_invalid_outbox_fixture_fails_schema(outbox_invalid_fixtures, outbox_schema_errors):
    for name, entry in outbox_invalid_fixtures:
        assert outbox_schema_errors(entry) != [], f"{name}: expected a schema violation"


def test_OB_05_enqueue_refuses_every_invalid_outbox_fixture(outbox_invalid_fixtures):
    """Schema validation runs before authorisation, so an empty evidence dict is enough here --
    enqueue must never reach tilo_policy.check_entry for a structurally invalid entry."""
    for name, entry in outbox_invalid_fixtures:
        emitted: list[dict] = []
        outbox = make_outbox(emitted)
        with pytest.raises(tilo_connectors.OutboxRefused):
            outbox.enqueue(entry, {})
        assert emitted == [], name
