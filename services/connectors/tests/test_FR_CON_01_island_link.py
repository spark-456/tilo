"""FR-CON-01 (PRD 12.1): every connector in this release is an API connector, so its island links
to the world by an API road. `ConnectorRegistry.island_link` says so; `list_for_world` keeps its
five keys (pinned in test_FR_CON_01_registry.py)."""

from __future__ import annotations

import pytest
from _registry_lib import CONTRACTS, MOCK_ID, load_json, mock_entry, write_config
from tilo_connectors.registry import load_registry


def test_FR_CON_01_every_registry_connector_links_as_api_road(tmp_path):
    entries = [load_json(p) for p in sorted((CONTRACTS / "fixtures" / "connector" / "valid").glob("*.json"))]
    entries.append(mock_entry())
    registry = load_registry(write_config(tmp_path, entries))

    for connector_id in registry.ids():
        assert registry.island_link(connector_id) == {"conn": "api", "bridge": "road"}
    assert registry.island_link(MOCK_ID) == {"conn": "api", "bridge": "road"}


def test_FR_CON_01_island_link_of_an_unknown_connector_is_a_key_error(tmp_path):
    registry = load_registry(write_config(tmp_path, [mock_entry()]))

    with pytest.raises(KeyError):
        registry.island_link("not_declared")


def test_FR_CON_01_changing_an_island_link_never_changes_the_next_one(tmp_path):
    registry = load_registry(write_config(tmp_path, [mock_entry()]))

    registry.island_link(MOCK_ID)["conn"] = "browser"

    assert registry.island_link(MOCK_ID) == {"conn": "api", "bridge": "road"}
