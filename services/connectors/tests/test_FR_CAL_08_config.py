"""FR-CAL-08 (config): the shipped google_calendar connector, read_events tier, working window and the
calendar_sync block, and the loader that checks them. API_FR_CAL_08.md "Shipped config", "Errors",
`load_calendar_sync_config`.

PRD addendum 3.4 FR-CAL-02 ("a task needing only read asks only for the read scope"), FR-CAL-08;
contracts/connector.schema.json (unchanged); BQ-CAL8-1 (config/personal.yaml), BQ-CAL8-7 (the read scope).
The shipped-config tests at the top need no new module and pass today; the loader tests fail with
ModuleNotFoundError: tilo_connectors.calendar_sync until it exists.
"""

from __future__ import annotations

import copy
import tomllib
from datetime import time

import pytest
import yaml
from _calendar_lib import (
    AUTONOMY_YAML,
    CALENDAR_READONLY,
    CONNECTORS_YAML,
    PERSONAL_YAML,
    REPO_ROOT,
)
from _oauth_lib import make_env, schema_errors

SYNC_KEYS = {"poll_interval_s", "past_days", "future_days", "max_pages", "backoff_base_s", "backoff_max_s"}
CALENDAR_EVENTS_OWNED = "https://www.googleapis.com/auth/calendar.events.owned"


def _connectors() -> list[dict]:
    return yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8"))


def _declaration() -> dict:
    found = [c for c in _connectors() if c["id"] == "google_calendar"]
    assert len(found) == 1, "config/connectors.yaml declares google_calendar exactly once"
    return found[0]


def _personal() -> dict:
    return yaml.safe_load(PERSONAL_YAML.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# config/connectors.yaml and config/autonomy.yaml


def test_FR_CAL_08_google_calendar_validates_against_the_unchanged_connector_schema():
    assert schema_errors("connector.schema.json", _declaration()) == []


def test_FR_CAL_08_reading_asks_only_calendar_readonly_and_the_only_write_scope_is_events_owned():
    """BQ-CAL8-7 pinned one scope under read. ADR-0035 decision 6 (FR-CAL-04) adds exactly one more, asked only
    for the write and send capabilities (tests/contracts FR_CON_02_ADR35_L1 pins the actions); nothing wider."""
    decl = _declaration()
    assert decl["auth"] == "oauth2"
    assert decl["scopes"]["read"] == [CALENDAR_READONLY], "exactly the one scope, under read (BQ-CAL8-7)"
    assert decl["scopes"] == {
        "read": [CALENDAR_READONLY],
        "write": [CALENDAR_EVENTS_OWNED],
        "send": [CALENDAR_EVENTS_OWNED],
    }
    assert decl["capabilities"] == ["read", "write", "send"]
    declared = {scope for scopes in decl["scopes"].values() for scope in scopes}
    assert declared == {CALENDAR_READONLY, CALENDAR_EVENTS_OWNED}, "no full calendar scope, no calendar.events"
    assert {a["capability"] for a in decl["actions"] if a["gate_type"] == "none"} == {"read"}, "only reads are ungated"


def test_FR_CAL_08_read_events_is_T1_ungated_and_reversible():
    action = next(a for a in _declaration()["actions"] if a["id"] == "read_events")
    assert (action["capability"], action["risk_tier"], action["gate_type"], action["irreversible"]) == (
        "read",
        "T1",
        "none",
        False,
    )


def test_FR_CAL_08_limits_and_data_class_are_the_pinned_ones():
    decl = _declaration()
    assert decl["limits"] == {"per_minute": 60, "batch_size": 2500}
    assert decl["data_class"] == {"returns": ["personal", "business"], "redact": []}


def test_FR_CAL_08_autonomy_lists_read_events_at_the_declared_tier():
    table = yaml.safe_load(AUTONOMY_YAML.read_text(encoding="utf-8"))["actions"]
    action = next(a for a in _declaration()["actions"] if a["id"] == "read_events")
    assert table["read_events"] == "T1" == action["risk_tier"]


def test_FR_CAL_08_the_registry_loads_google_calendar():
    from tilo_connectors.registry import load_registry

    registry = load_registry(CONNECTORS_YAML)

    assert "google_calendar" in registry
    assert registry.get("google_calendar")["scopes"]["read"] == [CALENDAR_READONLY]


def test_FR_CAL_08_a_task_needing_only_read_asks_only_for_the_read_scope():
    from tilo_connectors.consent import ConsentService
    from tilo_connectors.registry import load_registry

    env = make_env()
    registry = load_registry(CONNECTORS_YAML)
    service = ConsentService(
        connectors={"google_calendar": registry.get("google_calendar")},
        broker=env.broker,
        http=env.google,
        settings=env.settings,
        clock=env.clock,
        emit=env.emitted.append,
    )

    needed = service.scopes_needed(user_id="u_priya", connector="google_calendar", capabilities=["read"])

    assert needed == [CALENDAR_READONLY]


# ---------------------------------------------------------------------------
# config/personal.yaml


def test_FR_CAL_08_personal_yaml_working_window_is_nine_to_six_as_quoted_strings():
    window = _personal()["working_window"]

    assert window == {"start": "09:00", "end": "18:00"}


def test_FR_CAL_08_personal_yaml_calendar_sync_block_has_the_six_keys_and_sane_values():
    block = _personal()["calendar_sync"]

    assert set(block) == SYNC_KEYS
    assert all(isinstance(v, int) and not isinstance(v, bool) for v in block.values())
    assert block["poll_interval_s"] == 900
    assert 60 <= block["poll_interval_s"] <= 86400
    assert 0 <= block["past_days"] <= 31 and 1 <= block["future_days"] <= 731
    assert block["backoff_base_s"] <= block["backoff_max_s"] <= 86400
    assert 2 * block["max_pages"] < _declaration()["limits"]["per_minute"]


# ---------------------------------------------------------------------------
# The loader


def test_FR_CAL_08_the_loader_reads_the_shipped_files():
    from tilo_connectors.calendar_sync import DEFAULT_PERSONAL_CONFIG, load_calendar_sync_config
    from tilo_connectors.registry import load_registry

    assert DEFAULT_PERSONAL_CONFIG == PERSONAL_YAML

    config = load_calendar_sync_config(DEFAULT_PERSONAL_CONFIG, registry=load_registry(CONNECTORS_YAML))

    assert (config.window.start, config.window.end) == (time(9, 0), time(18, 0))
    block = _personal()["calendar_sync"]
    assert config.poll_interval_s == block["poll_interval_s"] == 900
    assert (config.past_days, config.future_days, config.max_pages) == (7, 366, 25)
    assert (config.backoff_base_s, config.backoff_max_s) == (60, 3600)
    assert (config.page_size, config.per_minute) == (2500, 60), "from google_calendar limits.batch_size and per_minute"


def _good() -> dict:
    return copy.deepcopy(_personal())


def _write(tmp_path, data) -> object:
    path = tmp_path / "personal.yaml"
    if isinstance(data, bytes):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _load(path, registry=None):
    from tilo_connectors.calendar_sync import load_calendar_sync_config
    from tilo_connectors.registry import load_registry

    return load_calendar_sync_config(
        path, registry=registry if registry is not None else load_registry(CONNECTORS_YAML)
    )


PLANTED = "ZZPLANTEDVALUEZZ"


def _mut(**path_values):
    """A bad personal.yaml: each key is `block__key` (working_window or calendar_sync) set to a value."""

    def build() -> dict:
        data = _good()
        for dotted, value in path_values.items():
            block, key = dotted.split("__", 1)
            data[block][key] = value
        return data

    return build


def _drop(top):
    def build() -> dict:
        data = _good()
        del data[top]
        return data

    return build


def _extra(top, key):
    def build() -> dict:
        data = _good()
        data[top][key] = 1
        return data

    return build


BAD_FILES = {
    "start not a time": _mut(working_window__start=PLANTED),
    "start without leading zero": _mut(working_window__start="9:00"),
    "start 24:00": _mut(working_window__start="24:00"),
    "end 09:60": _mut(working_window__end="09:60"),
    "end with seconds": _mut(working_window__end="18:00:00"),
    "start is an integer": _mut(working_window__start=540),
    "start is a bool": _mut(working_window__start=True),
    "start equals end": _mut(working_window__start="12:00", working_window__end="12:00"),
    "start after end": _mut(working_window__start="18:00", working_window__end="09:00"),
    "no working_window": _drop("working_window"),
    "no calendar_sync": _drop("calendar_sync"),
    "working_window not a mapping": lambda: {**_good(), "working_window": 5},
    "calendar_sync not a mapping": lambda: {**_good(), "calendar_sync": [1, 2]},
    "extra key in working_window": _extra("working_window", "weekends"),
    "extra key in calendar_sync": _extra("calendar_sync", "push"),
    "poll_interval bool": _mut(calendar_sync__poll_interval_s=True),
    "poll_interval float": _mut(calendar_sync__poll_interval_s=900.0),
    "poll_interval string": _mut(calendar_sync__poll_interval_s=PLANTED),
    "poll_interval 59": _mut(calendar_sync__poll_interval_s=59),
    "poll_interval 86401": _mut(calendar_sync__poll_interval_s=86401),
    "past_days -1": _mut(calendar_sync__past_days=-1),
    "past_days 32": _mut(calendar_sync__past_days=32),
    "future_days 0": _mut(calendar_sync__future_days=0),
    "future_days 732": _mut(calendar_sync__future_days=732),
    "max_pages 0": _mut(calendar_sync__max_pages=0),
    "max_pages 30 (2 x 30 is not below per_minute 60)": _mut(calendar_sync__max_pages=30),
    "backoff_base 0": _mut(calendar_sync__backoff_base_s=0),
    "backoff_base 3601": _mut(calendar_sync__backoff_base_s=3601),
    "backoff_max below base": _mut(calendar_sync__backoff_base_s=120, calendar_sync__backoff_max_s=119),
    "backoff_max 86401": _mut(calendar_sync__backoff_max_s=86401),
    "top level is a list": lambda: [1, 2, 3],
    "top level is a scalar": lambda: "just text",
}


@pytest.mark.parametrize("name", sorted(BAD_FILES))
def test_FR_CAL_08_the_loader_refuses_a_bad_file_and_never_echoes_the_value(tmp_path, name):
    from tilo_connectors.errors import CalendarConfigError

    path = _write(tmp_path, BAD_FILES[name]())

    with pytest.raises(CalendarConfigError) as caught:
        _load(path)

    assert issubclass(CalendarConfigError, ValueError)
    assert 0 < len(str(caught.value)) <= 500
    assert PLANTED not in str(caught.value), "the message names the key, never a value"


@pytest.mark.parametrize(
    "text",
    [
        "working_window: {start: '09:00', end: 18:00}\n" + yaml.safe_dump({"calendar_sync": _good()["calendar_sync"]}),
        "working_window: {start: 9:00, end: '18:00'}\n" + yaml.safe_dump({"calendar_sync": _good()["calendar_sync"]}),
    ],
    ids=["unquoted 18:00 is the integer 1080", "unquoted 9:00 is the integer 540"],
)
def test_FR_CAL_08_the_loader_refuses_a_time_that_yaml_read_as_an_integer(tmp_path, text):
    from tilo_connectors.errors import CalendarConfigError

    with pytest.raises(CalendarConfigError):
        _load(_write(tmp_path, text))


def test_FR_CAL_08_the_loader_refuses_aliases_bad_encoding_and_a_missing_file(tmp_path):
    from tilo_connectors.errors import CalendarConfigError

    aliased = "a: &x [1, 2]\nworking_window: {start: '09:00', end: '18:00'}\nb: *x\n" + yaml.safe_dump(
        {"calendar_sync": _good()["calendar_sync"]}
    )
    for data in (aliased, b"\xff\xfe\x00 not utf-8 \x80\x81"):
        with pytest.raises(CalendarConfigError):
            _load(_write(tmp_path, data))
    with pytest.raises(CalendarConfigError):
        _load(tmp_path / "does-not-exist.yaml")


def test_FR_CAL_08_the_loader_ignores_other_top_level_keys(tmp_path):
    data = _good()
    data["reminders"] = {"max_per_day": 3}  # CC-PEOPLE-2's keys
    data["attention_window"] = "anything"

    config = _load(_write(tmp_path, data))

    assert config.poll_interval_s == 900


def _registry_with(mutate=None, *, drop=False):
    from tilo_connectors.registry import ConnectorRegistry

    decl = copy.deepcopy(_declaration())
    if mutate:
        mutate(decl)
    return ConnectorRegistry({} if drop else {"google_calendar": decl})


def _set(path, value):
    def apply(decl):
        node = decl
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value

    return apply


BAD_REGISTRIES = {
    "no google_calendar": dict(drop=True),
    "a second scope": dict(
        mutate=_set(("scopes", "read"), [CALENDAR_READONLY, "https://www.googleapis.com/auth/calendar"])
    ),
    "a narrower scope (BQ-CAL8-7 changes the loader with the config)": dict(
        mutate=_set(("scopes", "read"), ["https://www.googleapis.com/auth/calendar.events.readonly"])
    ),
    "read_events gated": dict(mutate=_set(("actions", 0, "gate_type"), "approval")),
    "read_events T2": dict(mutate=_set(("actions", 0, "risk_tier"), "T2")),
    "read_events irreversible": dict(mutate=_set(("actions", 0, "irreversible"), True)),
    "read_events not a read": dict(mutate=_set(("actions", 0, "capability"), "write")),
    "per_minute null": dict(mutate=_set(("limits", "per_minute"), None)),
    "batch_size null": dict(mutate=_set(("limits", "batch_size"), None)),
    "batch_size 0": dict(mutate=_set(("limits", "batch_size"), 0)),
    "batch_size 2501": dict(mutate=_set(("limits", "batch_size"), 2501)),
    "per_minute 50 (2 x max_pages 25 is not below it)": dict(mutate=_set(("limits", "per_minute"), 50)),
}


@pytest.mark.parametrize("name", sorted(BAD_REGISTRIES))
def test_FR_CAL_08_the_loader_refuses_a_registry_that_breaks_the_connector_contract(name):
    from tilo_connectors.errors import CalendarConfigError

    with pytest.raises(CalendarConfigError):
        _load(PERSONAL_YAML, registry=_registry_with(**BAD_REGISTRIES[name]))


def test_FR_CAL_08_the_loader_accepts_the_edge_values_the_doc_allows(tmp_path):
    data = _good()
    data["working_window"] = {"start": "00:00", "end": "23:59"}
    data["calendar_sync"] = {
        "poll_interval_s": 60,
        "past_days": 0,
        "future_days": 731,
        "max_pages": 29,  # 2 x 29 = 58 < 60
        "backoff_base_s": 3600,
        "backoff_max_s": 86400,
    }

    config = _load(_write(tmp_path, data))

    assert (config.window.start, config.window.end) == (time(0, 0), time(23, 59))
    assert (config.poll_interval_s, config.past_days, config.future_days, config.max_pages) == (60, 0, 731, 29)


# ---------------------------------------------------------------------------
# Errors and dependencies


def test_FR_CAL_08_the_new_errors_exist_with_the_pinned_bases():
    from tilo_connectors.adapters import AdapterError, SyncTokenExpired
    from tilo_connectors.errors import CalendarConfigError, CalendarSyncRefused
    from tilo_connectors.errors import SyncTokenExpired as FromErrors

    assert SyncTokenExpired is FromErrors, "re-exported by tilo_connectors.adapters"
    assert issubclass(SyncTokenExpired, AdapterError) and SyncTokenExpired.status == 410
    assert issubclass(CalendarConfigError, ValueError) and issubclass(CalendarSyncRefused, ValueError)


def test_FR_CAL_08_tzdata_is_a_declared_dependency_with_its_licence_recorded():
    """Windows has no system zone database, so ZoneInfo('Asia/Kolkata') needs the tzdata wheel in dev
    (API doc, builder notes; root CLAUDE.md: record every dependency's licence)."""
    pyproject = tomllib.loads((REPO_ROOT / "services" / "connectors" / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = [d.lower().replace("_", "-") for d in pyproject["project"]["dependencies"]]
    rows = (REPO_ROOT / "docs" / "licences.md").read_text(encoding="utf-8").lower().splitlines()

    assert any(d.startswith("tzdata") for d in dependencies)
    assert any(r.startswith("|") and "tzdata" in r and "apache-2.0" in r for r in rows), (
        "a table row: tzdata, Apache-2.0"
    )
