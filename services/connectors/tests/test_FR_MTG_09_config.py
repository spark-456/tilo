"""FR-MTG-09 (config): the shipped `meeting_host` connector, its T3 listing in config/autonomy.yaml, the
`meeting_host` block of config/personal.yaml, the loader that checks them, and the fixtures these tests stand on.
API_FR_MTG_09.md "Shipped config", "Errors", `load_meeting_host_config`; ADR-0024 decisions 1 to 3, accepted
amendments 4 and 5; BQ-MTG09-4, BQ-MTG09-5, BQ-MTG09-9.

The tests that only read the shipped files or the contracts need no new module: the fixture tests pass today, the
shipped-config tests fail until MTG09-a adds the three config edits, and the loader tests fail with
ModuleNotFoundError: tilo_connectors.meeting_host until it exists.

B-007 (orchestrator, not a test): adding the `meeting_host` entry changes the Director's plan-stage replay key,
so `evals/tests/test_PL_LIVE_E2E_*` fail until `evals/tests/regen_live_e2e_fixture.py` regenerates
`evals/bank/live/B-007`. That script sets `LIVE=1` in its own process, so the orchestrator or the user runs it.
"""

from __future__ import annotations

import copy

import pytest
import yaml
from _connectors_lib import evidence_from_case
from _meeting_host_lib import (
    ACTION_TYPE,
    AUTONOMY_YAML,
    CALENDAR_EVENTS_OWNED,
    CALENDAR_READONLY,
    CONNECTOR_ID,
    CONNECTORS_YAML,
    DRAFT_KIND,
    EVENT_FIELDS,
    EVENTS_URL,
    EXACT_MAX,
    HOST_CALENDAR,
    PERSONAL_YAML,
    DraftArtifacts,
    build_card,
    build_case,
    default_persons,
    errs,
    host_decl,
    literal_gate,
    meeting,
    mh,
    mha,
    no_network_and_no_live,  # noqa: F401 - autouse guard
    shipped_decl,
    write_personal,
    write_registry,
)
from _oauth_lib import schema_errors
from tilo_policy import Assessment, SideEffectFacts, check_entry, load_risk_table

# ---------------------------------------------------------------------------
# The fixtures the FR-MTG-09 tests stand on are contract-valid (no contract change). These pass today.


def test_FR_MTG_09_no_contract_change_the_fixtures_validate_against_the_unchanged_contracts():
    assert schema_errors("connector.schema.json", host_decl()) == [], "a new connector entry validates as it is"
    assert schema_errors("meeting.schema.json", meeting()) == []
    for record in default_persons().values():
        assert schema_errors("person.schema.json", record) == []
    stored = DraftArtifacts().put_draft(b'{"kind":"meeting_event"}')
    assert schema_errors("artifact.schema.json", stored) == [], "the draft is an application/json unit artifact"


def test_FR_MTG_09_no_contract_change_the_outbox_entry_and_gate_card_the_spec_pins_validate():
    gate = literal_gate()
    assert len(gate["exact"]) <= EXACT_MAX
    case = build_case(None, gate)
    assert schema_errors("outbox.schema.json", case["entry"]) == []
    assert schema_errors("events/data/approval.requested.schema.json", case["reserved_by"]["data"]) == []
    assert schema_errors("events/data/approval.resolved.schema.json", case["authorised_by"]["data"]) == []
    requested = case["reserved_by"]["data"]
    assert (requested["risk_tier"], requested["irreversible"], requested["approver"], requested["team_lead"]) == (
        "T3",
        True,
        None,
        None,
    )
    assert (case["entry"]["action_type"], case["entry"]["connector"]) == (ACTION_TYPE, CONNECTOR_ID)
    assert case["entry"]["modifiers"] == ["new_recipients"] and case["entry"]["risk_tier"] == "T3"
    evidence = evidence_from_case(copy.deepcopy(case))
    assert check_entry({**evidence, "entry": case["entry"], "transfer": None, "rule": None}) is None, "OB-01, OB-05"
    card = build_card(gate)
    assert schema_errors("card.schema.json", card) == []
    assert card["gate"]["recipients"] == case["entry"]["recipients"], "CR-12"
    assert card["gate"]["action"]["item"] == case["entry"]["item"] == case["reserved_by"]["data"]["item"]


# ---------------------------------------------------------------------------
# config/connectors.yaml: exactly one connector, one action


def test_FR_MTG_09_connectors_yaml_declares_meeting_host_once_and_it_validates_unchanged():
    decl = shipped_decl()
    assert schema_errors("connector.schema.json", decl) == []
    entries = yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8"))
    assert [e["id"] for e in entries].count(CONNECTOR_ID) == 1


def test_FR_MTG_09_the_only_scope_is_calendar_events_owned_under_send_and_nothing_else_holds_it():
    decl = shipped_decl()
    assert decl["auth"] == "oauth2"
    assert decl["scopes"] == {"send": [CALENDAR_EVENTS_OWNED]}, "exactly the one scope, under send (ADR-0024 d2)"
    assert decl["capabilities"] == ["send"]
    entries = yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8"))
    for other in (e for e in entries if e["id"] not in (CONNECTOR_ID, "google_calendar")):
        assert "calendar.events" not in yaml.safe_dump(other), f"{other['id']} gains no calendar write scope"
    # ADR-0035 decision 6 (supersedes ADR-0024's "every google_calendar grant stays read-only"): a person's own
    # calendar gains the same scope under write and send, asked only when a task needs it, and nothing wider.
    calendar = next(e for e in entries if e["id"] == "google_calendar")
    assert calendar["scopes"] == {
        "read": [CALENDAR_READONLY],
        "write": [CALENDAR_EVENTS_OWNED],
        "send": [CALENDAR_EVENTS_OWNED],
    }
    assert calendar["capabilities"] == ["read", "write", "send"]


def test_FR_MTG_09_create_meeting_event_is_the_one_action_send_T3_approval_and_irreversible():
    (action,) = shipped_decl()["actions"]
    assert action["id"] == ACTION_TYPE == "create_meeting_event"
    assert (action["capability"], action["risk_tier"], action["gate_type"], action["irreversible"]) == (
        "send",
        "T3",
        "approval",
        True,
    )
    words = action["description"].lower()
    assert "bot" in words and "meet" in words, "the consent card says: sign in as the bot, and that a Meet link is made"
    assert len(action["description"]) <= 200


def test_FR_MTG_09_name_icon_limits_and_data_class_are_the_pinned_ones():
    decl = shipped_decl()
    assert (decl["name"], decl["icon"]) == ("Tilo meeting host", "calendar")
    assert decl["limits"] == {"per_minute": 30, "batch_size": 50}
    assert decl["data_class"] == {"returns": ["business"], "redact": []}


def test_FR_MTG_09_meeting_host_is_appended_after_google_calendar_and_the_first_four_stay():
    from tilo_connectors.registry import load_registry

    ids = load_registry(CONNECTORS_YAML).ids()
    assert ids[:4] == ("gmail", "google_drive", "lovable", "google_calendar"), "the Director's catalogue order holds"
    assert CONNECTOR_ID in ids and ids.index(CONNECTOR_ID) == 4


def test_FR_MTG_09_the_registry_loads_meeting_host_and_its_island_starts_locked():
    from tilo_connectors.registry import load_registry

    registry = load_registry(CONNECTORS_YAML)
    assert registry.get(CONNECTOR_ID) == shipped_decl()
    islands = {i["id"]: i for i in registry.list_for_world()}
    assert islands[CONNECTOR_ID]["state"] == "locked", "no connection event yet (HR-1)"


def test_FR_MTG_09_the_shipped_declaration_equals_the_one_in_the_api_doc_apart_from_its_words():
    shipped, pinned = shipped_decl(), host_decl()
    shipped["actions"][0].pop("description")
    pinned["actions"][0].pop("description")
    assert shipped == pinned


# ---------------------------------------------------------------------------
# config/autonomy.yaml and the policy engine (PE-14: always a person)


def test_FR_MTG_09_autonomy_lists_create_meeting_event_as_T3_explicitly():
    raw = yaml.safe_load(AUTONOMY_YAML.read_text(encoding="utf-8"))
    assert raw["actions"][ACTION_TYPE] == "T3", "listed, not left to the unlisted-is-T3 default"


def test_FR_MTG_09_policy_engine_assesses_create_meeting_event_as_T3_with_new_recipients():
    table = load_risk_table()
    got = table.assess(ACTION_TYPE, SideEffectFacts(recipients=("o@example.com",)))
    assert got == Assessment("T3", ("new_recipients",))
    assert table.tier_of(ACTION_TYPE, []) == "T3", "T3 even before any modifier applies"
    assert table.max_level["T3"] == "L1", "a policy never opens a T3 gate"


def test_FR_MTG_09_autonomy_yaml_still_loads_through_the_risk_table_schema():
    table = load_risk_table()  # PolicyConfigError when contracts/policy.schema.json refuses the file
    assert table.actions[ACTION_TYPE] == "T3" and table.actions["read_events"] == "T1"
    assert table.actions["build_handoff"] == "T3"


# ---------------------------------------------------------------------------
# config/personal.yaml


def test_FR_MTG_09_personal_yaml_has_meeting_host_max_duration_60_and_keeps_the_other_keys():
    raw = yaml.safe_load(PERSONAL_YAML.read_text(encoding="utf-8"))
    assert raw["meeting_host"] == {"max_duration_min": 60}
    assert raw["working_window"] == {"start": "09:00", "end": "18:00"}
    assert set(raw["calendar_sync"]) == {
        "poll_interval_s",
        "past_days",
        "future_days",
        "max_pages",
        "backoff_base_s",
        "backoff_max_s",
    }
    assert type(raw["meeting_host"]["max_duration_min"]) is int


def test_FR_MTG_09_the_three_config_files_still_validate_and_load_with_meeting_host_declared():
    from tilo_connectors.calendar_sync import DEFAULT_PERSONAL_CONFIG, load_calendar_sync_config
    from tilo_connectors.registry import load_registry

    registry = load_registry(CONNECTORS_YAML)  # every entry validates against connector.schema.json
    assert CONNECTOR_ID in registry
    load_risk_table()  # autonomy.yaml against policy.schema.json
    config = load_calendar_sync_config(DEFAULT_PERSONAL_CONFIG, registry=registry)  # ignores `meeting_host`
    assert config.poll_interval_s == 900
    assert mh().load_meeting_host_config(DEFAULT_PERSONAL_CONFIG, registry=registry).max_duration_min == 60


WIDER_CALENDAR_SCOPES = {
    "a broader write scope": {
        "read": [CALENDAR_READONLY],
        "write": ["https://www.googleapis.com/auth/calendar.events"],
    },
    "the full calendar scope": {"read": [CALENDAR_READONLY], "send": ["https://www.googleapis.com/auth/calendar"]},
    "a second write scope": {"read": [CALENDAR_READONLY], "write": [CALENDAR_EVENTS_OWNED, CALENDAR_READONLY]},
    "owned under read": {"read": [CALENDAR_READONLY, CALENDAR_EVENTS_OWNED]},
    "owned instead of readonly": {"read": [CALENDAR_EVENTS_OWNED]},
    "share with owned": {"read": [CALENDAR_READONLY], "share": [CALENDAR_EVENTS_OWNED]},
}


@pytest.mark.parametrize("name", sorted(WIDER_CALENDAR_SCOPES))
def test_FR_MTG_09_the_calendar_loader_still_refuses_a_google_calendar_declaration_wider_than_ADR_0035(tmp_path, name):
    """ADR-0035 sanctions exactly `calendar.events.owned` under write and send; the sync loader refuses any other."""
    from tilo_connectors.calendar_sync import load_calendar_sync_config
    from tilo_connectors.errors import CalendarConfigError
    from tilo_connectors.registry import load_registry

    entries = yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8"))
    for entry in entries:
        if entry["id"] == "google_calendar":
            entry["scopes"] = WIDER_CALENDAR_SCOPES[name]
    path = tmp_path / "connectors.yaml"
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    with pytest.raises(CalendarConfigError):
        load_calendar_sync_config(PERSONAL_YAML, registry=load_registry(path))


# ---------------------------------------------------------------------------
# tilo_connectors.meeting_host: names the API doc pins


def test_FR_MTG_09_module_constants_are_the_pinned_ones():
    assert mh().CONNECTOR_ID == CONNECTOR_ID == "meeting_host"
    assert mh().ACTION_TYPE == ACTION_TYPE == "create_meeting_event"
    assert mh().CALENDAR_EVENTS_OWNED == CALENDAR_EVENTS_OWNED
    assert mh().HOST_CALENDAR == HOST_CALENDAR == "primary"
    assert mh().DRAFT_KIND == DRAFT_KIND == "meeting_event"
    assert mh().EXACT_MAX == EXACT_MAX == 500


def test_FR_MTG_09_adapter_module_constants_are_the_pinned_ones_and_ask_google_for_no_link():
    assert mha().EVENTS_URL == EVENTS_URL
    assert mha().EVENT_FIELDS == EVENT_FIELDS
    assert "hangoutLink" not in mha().EVENT_FIELDS and "entryPoints" not in mha().EVENT_FIELDS
    assert "htmlLink" not in mha().EVENT_FIELDS and "attendees" not in mha().EVENT_FIELDS


def test_FR_MTG_09_the_error_types_exist_with_the_pinned_shape():
    refused, config_error = errs().MeetingHostRefused, errs().MeetingHostConfigError
    assert issubclass(refused, ValueError) and issubclass(config_error, ValueError)
    assert issubclass(errs().PossiblySent, errs().SideEffectRefused), "the adapter raises these existing types"


def test_FR_MTG_09_config_error_message_is_cut_at_500_characters_and_names_a_key_never_a_value():
    long = "x" * 900
    error = errs().MeetingHostConfigError(long)
    assert len(str(error)) <= 500


# ---------------------------------------------------------------------------
# load_meeting_host_config


def test_FR_MTG_09_the_loader_reads_the_shipped_files_and_defaults_to_the_shipped_personal_config():
    from tilo_connectors.calendar_sync import DEFAULT_PERSONAL_CONFIG
    from tilo_connectors.registry import load_registry

    registry = load_registry(CONNECTORS_YAML)
    config = mh().load_meeting_host_config(registry=registry)  # the default path
    assert config == mh().MeetingHostConfig(max_duration_min=60)
    assert config == mh().load_meeting_host_config(DEFAULT_PERSONAL_CONFIG, registry=registry)


@pytest.mark.parametrize("minutes", [1, 30, 60, 90, 1440])
def test_FR_MTG_09_the_loader_accepts_a_duration_from_1_to_1440(tmp_path, minutes):
    path = write_personal(tmp_path, {"max_duration_min": minutes})
    assert mh().load_meeting_host_config(path, registry=write_registry(tmp_path)).max_duration_min == minutes


@pytest.mark.parametrize("bad", [0, -1, 1441, 10**9, True, False, "60", 60.0, 59.5, None, [60], {"a": 1}])
def test_FR_MTG_09_the_loader_refuses_a_bool_non_int_or_out_of_range_duration(tmp_path, bad):
    path = write_personal(tmp_path, {"max_duration_min": bad})
    with pytest.raises(errs().MeetingHostConfigError) as raised:
        mh().load_meeting_host_config(path, registry=write_registry(tmp_path))
    assert "max_duration_min" in str(raised.value), "it names the key"
    assert len(str(raised.value)) <= 500


def test_FR_MTG_09_the_config_error_never_echoes_the_value(tmp_path):
    secret_looking = "SECRETVALUE-" + "z" * 40
    path = write_personal(tmp_path, {"max_duration_min": secret_looking})
    with pytest.raises(errs().MeetingHostConfigError) as raised:
        mh().load_meeting_host_config(path, registry=write_registry(tmp_path))
    assert secret_looking not in str(raised.value) and "SECRETVALUE" not in str(raised.value)


def test_FR_MTG_09_the_loader_refuses_a_missing_meeting_host_block(tmp_path):
    path = write_personal(tmp_path, drop=True)
    with pytest.raises(errs().MeetingHostConfigError) as raised:
        mh().load_meeting_host_config(path, registry=write_registry(tmp_path))
    assert "meeting_host" in str(raised.value)


@pytest.mark.parametrize(
    "block",
    [
        {},
        {"max_duration_min": 60, "extra": 1},
        {"max_duration_min": 60, "max_attendees": 50},
        {"duration": 60},
        None,
        [],
        [{"max_duration_min": 60}],
        "60",
        60,
    ],
)
def test_FR_MTG_09_the_loader_refuses_a_key_other_than_max_duration_min_or_a_block_that_is_not_a_mapping(
    tmp_path, block
):
    path = tmp_path / "personal.yaml"
    raw = yaml.safe_load(PERSONAL_YAML.read_text(encoding="utf-8"))
    raw["meeting_host"] = block
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(errs().MeetingHostConfigError):
        mh().load_meeting_host_config(path, registry=write_registry(tmp_path))


def test_FR_MTG_09_the_loader_refuses_an_unreadable_file_with_a_fixed_text(tmp_path):
    for content in (b"\xff\xfe\x00bad", b"meeting_host: [unclosed", b"- a\n- b\n"):
        path = tmp_path / "personal.yaml"
        path.write_bytes(content)
        with pytest.raises(errs().MeetingHostConfigError):
            mh().load_meeting_host_config(path, registry=write_registry(tmp_path))
    with pytest.raises(errs().MeetingHostConfigError):
        mh().load_meeting_host_config(tmp_path / "missing.yaml", registry=write_registry(tmp_path))


def test_FR_MTG_09_the_loader_refuses_a_registry_without_meeting_host(tmp_path):
    from tilo_connectors.registry import load_registry

    other = tmp_path / "other.yaml"
    entries = [e for e in yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8")) if e["id"] != CONNECTOR_ID]
    other.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    with pytest.raises(errs().MeetingHostConfigError):
        mh().load_meeting_host_config(write_personal(tmp_path), registry=load_registry(other))


def _variant(**changes):
    decl = host_decl()
    for key, value in changes.items():
        if key.startswith("action_"):
            decl["actions"][0][key.removeprefix("action_")] = value
        else:
            decl[key] = value
    return decl


VARIANTS = {
    "a wider scope on send": _variant(scopes={"send": [CALENDAR_EVENTS_OWNED, CALENDAR_READONLY]}),
    "the wider calendar.events scope": _variant(scopes={"send": ["https://www.googleapis.com/auth/calendar.events"]}),
    "a second capability with a scope": _variant(
        scopes={"send": [CALENDAR_EVENTS_OWNED], "read": [CALENDAR_READONLY]}, capabilities=["send", "read"]
    ),
    "no scope": _variant(scopes={}),
    "the scope under write": _variant(scopes={"write": [CALENDAR_EVENTS_OWNED]}),
    "tier T2": _variant(action_risk_tier="T2"),
    "tier T1": _variant(action_risk_tier="T1"),
    "reversible": _variant(action_irreversible=False),
    "capability write": _variant(action_capability="write"),
    "another action id": _variant(action_id="create_event"),
}


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_FR_MTG_09_MH_07_the_loader_refuses_a_declaration_that_is_not_the_pinned_one(tmp_path, name):
    decl = VARIANTS[name]
    assert schema_errors("connector.schema.json", decl) == [], "the variant is a schema-valid declaration"
    with pytest.raises(errs().MeetingHostConfigError):
        mh().load_meeting_host_config(write_personal(tmp_path), registry=write_registry(tmp_path, decl))


def test_FR_MTG_09_MH_07_the_loader_accepts_the_pinned_declaration_with_other_words(tmp_path):
    decl = host_decl()
    decl["actions"][0]["description"] = "Make the meeting on the bot's account."
    config = mh().load_meeting_host_config(write_personal(tmp_path), registry=write_registry(tmp_path, decl))
    assert config.max_duration_min == 60
