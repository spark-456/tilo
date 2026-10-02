"""FR-CON-01 (PRD 12.1, 12.6): "Connector contract and registry from config."
Acceptance: "Adding a mock connector by config makes it appear as an island with its scopes."

Public API these tests pin (new module `tilo_connectors.registry`):

    class ConnectorConfigError(ValueError)
    load_registry(path: str | os.PathLike) -> ConnectorRegistry
    ConnectorRegistry:
        ids() -> tuple[str, ...]                      declaration order
        get(connector_id: str) -> Mapping             the declaration, connector.schema.json shape;
                                                      KeyError for an unknown id
        __contains__(connector_id), __len__()
        list_for_world(events: Iterable[Mapping] = ()) -> list[dict]
            one island per connector, in declaration order, each exactly
            {"id", "name", "icon", "scopes", "state"}; `state` is the layout contract's island
            state (contracts/layout.schema.json: locked, requested, connected, failed) computed
            from the recorded connection.* events, last event for the connector wins.

Defaults chosen where the PRD is silent (listed in the ticket report):
* config file = top-level YAML list of connector.schema.json entries (as config/teams.yaml).
* island label is the connector's `name` (the contract's "Island name in the world").
* connection state comes only from recorded connection.* events (PRD 9.5, HR-1: nothing without an
  event); events are passed in seq order; no event, or connection.revoked, is "locked".
"""

from __future__ import annotations

import copy
import json
import pathlib
import tempfile

import jsonschema
import pytest
from _registry_lib import (
    CONTRACTS,
    EVENT_TO_STATE,
    MOCK_ID,
    connection_event,
    load_json,
    mock_entry,
    valid_connector,
    write_config,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

INVALID_DIR = CONTRACTS / "fixtures" / "connector" / "invalid"
VALID_DIR = CONTRACTS / "fixtures" / "connector" / "valid"
INVALID = sorted(INVALID_DIR.glob("*.json"))
VALID = sorted(VALID_DIR.glob("*.json"))
BASE = "https://contracts.tilo.example"
ISLAND_KEYS = {"id", "name", "icon", "scopes", "state"}


def registry_module():
    from tilo_connectors import registry

    return registry


def load(path):
    return registry_module().load_registry(path)


# --- acceptance: a mock connector added by config appears as an island with its scopes --------


def test_FR_CON_01_adding_a_mock_connector_by_config_makes_it_an_island_with_its_scopes(tmp_path):
    before = load(write_config(tmp_path, [valid_connector("gmail")], "before.yaml"))
    after = load(write_config(tmp_path, [valid_connector("gmail"), mock_entry()], "after.yaml"))

    islands_before = before.list_for_world()
    islands_after = after.list_for_world()

    assert [i["id"] for i in islands_before] == ["gmail"]
    assert [i["id"] for i in islands_after] == ["gmail", MOCK_ID]
    assert islands_after[0] == islands_before[0]  # adding one changes nothing about the others
    mock_island = islands_after[1]
    assert mock_island["name"] == "Mock Mail"
    assert mock_island["icon"] == "mail"
    assert mock_island["scopes"] == mock_entry()["scopes"]
    assert mock_island["scopes"]["send"] == ["https://mock.example/auth/mail.send"]


def test_FR_CON_01_every_shipped_valid_connector_loads_as_an_island(tmp_path):
    assert VALID, "contracts/fixtures/connector/valid must hold at least one connector"
    entries = [load_json(p) for p in VALID]
    registry = load(write_config(tmp_path, entries))

    assert registry.ids() == tuple(e["id"] for e in entries)
    assert len(registry) == len(entries)
    for entry in entries:
        assert entry["id"] in registry
        assert registry.get(entry["id"]) == entry  # the declaration round-trips unchanged
    islands = {i["id"]: i for i in registry.list_for_world()}
    for entry in entries:
        assert islands[entry["id"]]["scopes"] == entry["scopes"]


def test_FR_CON_01_an_empty_config_is_a_valid_empty_registry(tmp_path):
    registry = load(write_config(tmp_path, []))

    assert len(registry) == 0
    assert registry.ids() == ()
    assert registry.list_for_world() == []


def test_FR_CON_01_get_of_an_unknown_connector_is_a_key_error(tmp_path):
    registry = load(write_config(tmp_path, [mock_entry()]))

    with pytest.raises(KeyError):
        registry.get("not_declared")
    assert "not_declared" not in registry


# --- every config entry validates against contracts/connector.schema.json ---------------------


def test_FR_CON_01_the_registry_accepts_exactly_what_connector_schema_accepts(tmp_path, schema_registry):
    schema = load_json(CONTRACTS / "connector.schema.json")
    validator = jsonschema.Draft202012Validator(schema, registry=schema_registry)
    cases = [(p, load_json(p)) for p in VALID + INVALID]
    assert len(cases) >= 13

    for path, entry in cases:
        schema_ok = not list(validator.iter_errors(entry))
        config = write_config(tmp_path, [entry], f"{path.stem}.yaml")
        if schema_ok:
            assert load(config).ids() == (entry["id"],), path.name
        else:
            with pytest.raises(registry_module().ConnectorConfigError):
                load(config)


@pytest.mark.parametrize("fixture", INVALID, ids=lambda p: p.stem)
def test_FR_CON_01_an_invalid_entry_fails_startup_with_an_error_naming_the_connector(tmp_path, fixture):
    entry = load_json(fixture)
    entry["id"] = "bad_one"
    config = write_config(tmp_path, [mock_entry(), entry])

    with pytest.raises(registry_module().ConnectorConfigError) as caught:
        load(config)

    message = str(caught.value)
    assert "bad_one" in message  # clear: which entry
    assert len(message) > len("bad_one")  # and something about what is wrong with it


def test_FR_CON_01_an_action_without_a_risk_tier_fails_startup_naming_the_field(tmp_path):
    """FR-CON-06 is linted on the schema already (tests/contracts); here only that the loader
    applies that schema, so a connector with an untiered action never reaches the registry."""
    entry = mock_entry()
    del entry["actions"][1]["risk_tier"]

    with pytest.raises(registry_module().ConnectorConfigError) as caught:
        load(write_config(tmp_path, [entry]))

    assert "risk_tier" in str(caught.value)
    assert MOCK_ID in str(caught.value)


def test_FR_CON_01_an_unknown_field_in_an_entry_is_refused(tmp_path):
    entry = mock_entry()
    entry["mcp_server_url"] = "https://mock.example/mcp"  # not in connector.schema.json

    with pytest.raises(registry_module().ConnectorConfigError):
        load(write_config(tmp_path, [entry]))


@pytest.mark.parametrize(
    "content",
    [
        "{not: [valid yaml",
        "connectors: {}\n",  # a mapping, not the list of entries
        "- just a string\n",
        "- 42\n",
    ],
    ids=["unparseable", "root_is_a_mapping", "entry_is_a_string", "entry_is_a_number"],
)
def test_FR_CON_01_a_config_that_is_not_a_list_of_entries_fails_startup(tmp_path, content):
    config = tmp_path / "connectors.yaml"
    config.write_text(content, encoding="utf-8")

    with pytest.raises(registry_module().ConnectorConfigError):
        load(config)


def test_FR_CON_01_nothing_is_partially_registered_when_a_later_entry_is_invalid(tmp_path):
    """The invalid entry comes last, after a valid one. load_registry raises instead of returning
    a registry that holds the first one, and a failed load leaves no state behind: the next load of
    a good file holds exactly its own connectors."""
    bad = mock_entry("second_one")
    del bad["actions"][0]["risk_tier"]
    with pytest.raises(registry_module().ConnectorConfigError):
        load(write_config(tmp_path, [valid_connector("gmail"), bad], "bad.yaml"))

    clean = load(write_config(tmp_path, [valid_connector("web_search")], "good.yaml"))

    assert clean.ids() == ("web_search",)
    assert "gmail" not in clean
    assert [i["id"] for i in clean.list_for_world()] == ["web_search"]


# --- duplicate ids are refused ------------------------------------------------------------------


def test_FR_CON_01_duplicate_connector_ids_are_refused(tmp_path):
    first, second = mock_entry(), mock_entry()
    second["name"] = "Other Mail"  # same id, different content: still a duplicate

    with pytest.raises(registry_module().ConnectorConfigError) as caught:
        load(write_config(tmp_path, [first, valid_connector("gmail"), second]))

    assert MOCK_ID in str(caught.value)


def test_FR_CON_01_a_byte_identical_duplicate_is_refused_too(tmp_path):
    with pytest.raises(registry_module().ConnectorConfigError):
        load(write_config(tmp_path, [mock_entry(), mock_entry()]))


# --- every action declares a risk tier ----------------------------------------------------------


def test_FR_CON_01_every_loaded_action_carries_its_declared_risk_tier_and_gate(tmp_path):
    entries = [load_json(p) for p in VALID] + [mock_entry()]
    registry = load(write_config(tmp_path, entries))

    for entry in entries:
        loaded = registry.get(entry["id"])
        assert len(loaded["actions"]) >= 1
        for declared, action in zip(entry["actions"], loaded["actions"], strict=True):
            assert action["id"] == declared["id"]
            assert action["risk_tier"] in ("T1", "T2", "T3")
            assert action["risk_tier"] == declared["risk_tier"]
            assert action["gate_type"] == declared["gate_type"]


# --- the registry is read-only after load -------------------------------------------------------


def test_FR_CON_01_the_registry_has_no_way_to_add_or_remove_a_connector_after_load(tmp_path):
    registry = load(write_config(tmp_path, [mock_entry()]))

    for name in ("register", "add", "remove", "unregister", "set", "put", "clear", "update", "reload", "pop"):
        assert not hasattr(registry, name), f"registry exposes a mutator {name!r}"
    with pytest.raises(TypeError):
        registry["new_one"] = mock_entry("new_one")  # type: ignore[index]


def test_FR_CON_01_changing_what_get_returns_never_changes_the_registry(tmp_path):
    registry = load(write_config(tmp_path, [mock_entry()]))
    original = copy.deepcopy(mock_entry())

    declaration = registry.get(MOCK_ID)
    for mutate in (
        lambda d: d.__setitem__("name", "Hacked"),
        lambda d: d["scopes"]["send"].append("https://evil.example/all"),
        lambda d: d["actions"][1].__setitem__("risk_tier", "T1"),
        lambda d: d["actions"].append({"id": "extra"}),
    ):
        try:
            mutate(declaration)
        except (TypeError, AttributeError):
            pass  # an immutable view refusing the write is as good as a defensive copy

    assert registry.get(MOCK_ID) == original
    assert registry.list_for_world()[0]["scopes"] == original["scopes"]


def test_FR_CON_01_changing_what_list_for_world_returns_never_changes_the_registry(tmp_path):
    registry = load(write_config(tmp_path, [mock_entry()]))
    original = copy.deepcopy(mock_entry())

    islands = registry.list_for_world()
    islands[0]["scopes"]["send"].append("https://evil.example/all")
    islands[0]["state"] = "connected"
    islands.clear()

    again = registry.list_for_world()
    assert len(again) == 1
    assert again[0]["scopes"] == original["scopes"]
    assert again[0]["state"] == "locked"
    assert registry.get(MOCK_ID) == original


def test_FR_CON_01_editing_the_config_file_after_load_does_not_change_the_loaded_registry(tmp_path):
    config = write_config(tmp_path, [mock_entry()])
    registry = load(config)

    write_config(tmp_path, [valid_connector("gmail")])

    assert registry.ids() == (MOCK_ID,)
    assert [i["id"] for i in registry.list_for_world()] == [MOCK_ID]


# --- listing connectors for the world: what the island rendering needs --------------------------


def test_FR_CON_01_an_island_has_exactly_id_name_icon_scopes_and_connection_state(tmp_path):
    registry = load(write_config(tmp_path, [valid_connector("gmail"), mock_entry()]))

    islands = registry.list_for_world()

    assert len(islands) == 2
    for island in islands:
        assert set(island) == ISLAND_KEYS


def test_FR_CON_01_island_fields_are_the_ones_the_contracts_define(tmp_path, schema_registry):
    layout = load_json(CONTRACTS / "layout.schema.json")
    state_values = layout["$defs"]["island"]["properties"]["state"]["enum"]
    assert state_values == ["locked", "requested", "connected", "failed"]
    entries = [valid_connector("gmail"), valid_connector("web_search"), mock_entry()]
    registry = load(write_config(tmp_path, entries))

    for entry, island in zip(entries, registry.list_for_world(), strict=True):
        assert island["id"] == entry["id"]
        assert island["name"] == entry["name"]  # "Island name in the world"
        assert island["icon"] == entry["icon"]
        assert island["scopes"] == entry["scopes"]
        assert island["state"] in state_values
        jsonschema.validate(
            island["id"], {"$ref": f"{BASE}/common.schema.json#/$defs/connector_id"}, registry=schema_registry
        )
        jsonschema.validate(
            island["name"], {"$ref": f"{BASE}/common.schema.json#/$defs/plain_name"}, registry=schema_registry
        )
        jsonschema.validate(
            island["icon"], {"$ref": f"{BASE}/common.schema.json#/$defs/icon_name"}, registry=schema_registry
        )
        jsonschema.validate(
            island["scopes"], {"$ref": f"{BASE}/connector.schema.json#/$defs/scopes"}, registry=schema_registry
        )
    json.dumps(registry.list_for_world())  # plain data: it crosses to the renderer as JSON


def test_FR_CON_01_a_connector_with_no_connection_event_is_locked(tmp_path):
    registry = load(write_config(tmp_path, [valid_connector("gmail"), mock_entry()]))

    assert [i["state"] for i in registry.list_for_world()] == ["locked", "locked"]
    assert [i["state"] for i in registry.list_for_world(events=[])] == ["locked", "locked"]


@pytest.mark.parametrize(("event_type", "state"), sorted(EVENT_TO_STATE.items()))
def test_FR_CON_01_connection_events_set_the_island_state_per_prd_9_5(tmp_path, event_type, state):
    registry = load(write_config(tmp_path, [valid_connector("gmail"), mock_entry()]))

    islands = {i["id"]: i for i in registry.list_for_world([connection_event(event_type, MOCK_ID)])}

    assert islands[MOCK_ID]["state"] == state
    assert islands["gmail"]["state"] == "locked"  # an event about one connector moves only its island


def test_FR_CON_01_the_last_connection_event_for_a_connector_wins(tmp_path):
    registry = load(write_config(tmp_path, [mock_entry()]))
    lifecycle = [
        connection_event("connection.requested", MOCK_ID, 1),
        connection_event("connection.consented", MOCK_ID, 2),
        connection_event("connection.established", MOCK_ID, 3),
        connection_event("connection.expired", MOCK_ID, 4),
    ]
    expected = ["requested", "requested", "connected", "failed"]

    for upto, state in enumerate(expected, start=1):
        assert registry.list_for_world(lifecycle[:upto])[0]["state"] == state

    reconnect = [*lifecycle, connection_event("connection.revoked", MOCK_ID, 5)]
    assert registry.list_for_world(reconnect)[0]["state"] == "locked"
    again = [*reconnect, connection_event("connection.requested", MOCK_ID, 6)]
    assert registry.list_for_world(again)[0]["state"] == "requested"


def test_FR_CON_01_events_for_undeclared_connectors_and_other_families_change_nothing(tmp_path):
    registry = load(write_config(tmp_path, [mock_entry()]))
    other_family = load_json(CONTRACTS / "fixtures" / "events" / "valid" / "data.transfer.json")
    other_family["data"]["connector"] = MOCK_ID
    events = [connection_event("connection.established", "never_declared", 1), other_family]

    islands = registry.list_for_world(events)

    assert [(i["id"], i["state"]) for i in islands] == [(MOCK_ID, "locked")]  # no island appears for them


def test_FR_CON_01_list_for_world_does_not_mutate_its_events_and_accepts_any_iterable(tmp_path):
    registry = load(write_config(tmp_path, [mock_entry()]))
    events = [
        connection_event("connection.requested", MOCK_ID, 1),
        connection_event("connection.established", MOCK_ID, 2),
    ]
    snapshot = copy.deepcopy(events)

    from_list = registry.list_for_world(events)
    from_generator = registry.list_for_world(e for e in events)

    assert events == snapshot
    assert from_list == from_generator
    assert from_list[0]["state"] == "connected"


# --- properties -----------------------------------------------------------------------------------

_CONNECTOR_IDS = st.from_regex(r"[a-z][a-z0-9_]{1,31}", fullmatch=True)
_EVENT_TYPES = st.sampled_from(sorted(EVENT_TO_STATE))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ids=st.lists(_CONNECTOR_IDS, min_size=0, max_size=6, unique=True))
def test_FR_CON_01_property_one_island_per_declared_connector_in_declaration_order(ids):
    entries = [mock_entry(i) for i in ids]
    with tempfile.TemporaryDirectory() as tmp:
        registry = load(write_config(pathlib.Path(tmp), entries))

    assert registry.ids() == tuple(ids)
    assert [i["id"] for i in registry.list_for_world()] == ids
    assert len({i["id"] for i in registry.list_for_world()}) == len(ids)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ids=st.lists(_CONNECTOR_IDS, min_size=1, max_size=4, unique=True), data=st.data())
def test_FR_CON_01_property_duplicate_ids_are_always_refused(ids, data):
    duplicate = data.draw(st.sampled_from(ids))
    entries = [mock_entry(i) for i in ids] + [mock_entry(duplicate)]
    with tempfile.TemporaryDirectory() as tmp:
        config = write_config(pathlib.Path(tmp), entries)
        with pytest.raises(registry_module().ConnectorConfigError):
            load(config)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(sequence=st.lists(st.tuples(st.sampled_from(["a_conn", "b_conn", "c_conn"]), _EVENT_TYPES), max_size=12))
def test_FR_CON_01_property_state_is_a_pure_function_of_the_last_event_per_connector(sequence):
    entries = [mock_entry("a_conn"), mock_entry("b_conn")]  # c_conn is never declared
    with tempfile.TemporaryDirectory() as tmp:
        registry = load(write_config(pathlib.Path(tmp), entries))
    events = [connection_event(t, c, seq) for seq, (c, t) in enumerate(sequence, start=1)]
    snapshot = copy.deepcopy(events)

    first = registry.list_for_world(events)
    second = registry.list_for_world(events)

    assert first == second  # deterministic
    assert events == snapshot  # input untouched
    assert [i["id"] for i in first] == ["a_conn", "b_conn"]
    for island in first:
        last = [t for c, t in sequence if c == island["id"]]
        assert island["state"] == (EVENT_TO_STATE[last[-1]] if last else "locked")
        assert island["state"] in ("locked", "requested", "connected", "failed")
