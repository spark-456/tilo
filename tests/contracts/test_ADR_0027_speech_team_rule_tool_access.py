"""ADR-0027 (Proposed, 2026-10-08): the speech role and its audio price (providers 1.2.0), the team_rule.changed event
(registry 1.2.0) and a skill's tool_access (skill 1.1.0, common 1.5.0 tool_access_level). All additive: every shipped
config file and every older fixture stays valid."""

from __future__ import annotations

import sys

import pytest
import yaml
from _lib import errors_for, load_json, load_schema

MUST_ASK = ("spend", "share", "undo")


def _version(schema):
    return tuple(int(p) for p in schema["x-version"].split("."))


def _data_errors(repo_root, registry, data):
    return errors_for(load_schema(repo_root, "events/data/team_rule.changed"), data, registry)


def test_FR_MTG_17_PL_06_a_price_gains_an_optional_audio_input_and_the_speech_role_is_named(repo_root):
    schema = load_schema(repo_root, "providers")
    assert _version(schema) >= (1, 2, 0) and _version(schema)[0] == 1
    price = schema["$defs"]["price"]
    assert price["required"] == ["input", "output"], "audio_input stays optional"
    assert price["properties"]["audio_input"] == {"type": ["number", "null"], "minimum": 0}
    assert "speech" in schema["$defs"]["models"]["properties"]["roles"]["description"]


@pytest.mark.parametrize(
    "name",
    ["models.yaml", "models.dev.yaml", "models.gemini.yaml", "models.nim.yaml", "prices.yaml", "prices.dev.yaml"],
)
def test_PL_06_every_shipped_provider_config_stays_valid(repo_root, registry, name):
    providers = load_schema(repo_root, "providers")
    part = "models" if name.startswith("models") else "prices"
    doc = yaml.safe_load((repo_root / "config" / name).read_text(encoding="utf-8"))
    schema = {"$ref": f"https://contracts.tilo.example/providers.schema.json#/$defs/{part}"}
    assert providers["$defs"][part] and not errors_for(schema, doc, registry)


def test_FR_TEAM_04_team_rule_changed_is_registered_and_authorises_nothing(repo_root):
    registry_yaml = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    entry = registry_yaml["types"]["team_rule.changed"]
    assert (entry["family"], entry["verb"], entry["pillar"], entry["side_effect"]) == (
        "team_rule",
        "changed",
        "P4",
        False,
    )
    assert "authz_by" not in entry
    side_effects = load_schema(repo_root, "event")["if"]["properties"]["type"]["enum"]
    assert "team_rule.changed" not in side_effects


@pytest.mark.parametrize("key", MUST_ASK)
@pytest.mark.parametrize("before", ["on", "off"])
def test_FR_TEAM_04_a_must_ask_switch_is_never_switched_off(repo_root, registry, key, before):
    assert _data_errors(repo_root, registry, {"rule": "switch", "key": key, "from": before, "to": "off"})
    assert not _data_errors(repo_root, registry, {"rule": "switch", "key": key, "from": before, "to": "on"})


@pytest.mark.parametrize("name", ["team_rule.changed", "team_rule.changed--tool_access"])
def test_FR_TEAM_04_the_fixtures_are_owner_only_desk_events_that_pass_every_event_rule(repo_root, name):
    event = load_json(repo_root / f"contracts/fixtures/events/valid/{name}.json")
    assert (event["vis"], event["district"], event["authz"]) == ([], None, None)
    assert event["actor"] == event["target"] and event["actor"].startswith("u_")
    assert event["world_id"].startswith("w_desk_")
    sys.path.insert(0, str(repo_root / "scripts"))
    import contracts_codegen
    import contracts_events

    validate = contracts_codegen.validator(contracts_codegen.load_schemas())
    rules = contracts_events.load_registry(repo_root / "contracts")
    assert contracts_events.event_problems(event, rules, validate) == []


def test_FR_ACC_02_a_skill_maps_connectors_to_levels_and_older_skills_stay_valid(repo_root, registry):
    skill, common = load_schema(repo_root, "skill"), load_schema(repo_root, "common")
    assert _version(skill) >= (1, 1, 0) and _version(common) >= (1, 5, 0)
    assert common["$defs"]["tool_access_level"]["enum"] == ["off", "read", "draft", "act"]
    assert "tool_access" not in skill["required"]
    old = load_json(repo_root / "contracts/fixtures/skill/valid/web_research_citations.json")
    assert "tool_access" not in old and not errors_for(skill, old, registry)
    assert not errors_for(skill, {**old, "tool_access": {"gmail": "off", "google_drive": "act"}}, registry)
    assert errors_for(skill, {**old, "tool_access": {"gmail": "admin"}}, registry)
