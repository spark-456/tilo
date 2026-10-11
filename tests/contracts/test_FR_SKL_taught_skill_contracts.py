"""FR-SKL-01 to 07 (ADR-0034, Proposed): taught_skill.schema.json 1.0.0 (a sibling of skill.yaml), its try run, rating,
fix and helpers report, the six skill.* events (registry 1.4.0) and the capture video types (common 1.7.0)."""

from __future__ import annotations

import copy
import sys

import pytest
import yaml
from _lib import errors_for, list_fixtures, load_json, load_schema

ROOT = "https://contracts.tilo.example/taught_skill.schema.json"
FOLDERS = ["taught_skill", *(f"taught_skill.{d}" for d in ("try_run_result", "rating", "fix", "helpers_report"))]
EVENTS = ["captured", "version_proposed", "try_run", "state_changed", "rated", "fixed"]
MUST_ASK = ["send", "post", "pay", "delete", "share", "book"]
TEXT_FIELDS = {"text", "note", "name", "label", "summary", "title", "content"}


def _version(schema):
    return tuple(int(p) for p in schema["x-version"].split("."))


def _ref(folder):
    _, _, key = folder.partition(".")
    return {"$ref": ROOT + (f"#/$defs/{key}" if key else "")}


@pytest.mark.parametrize("folder", FOLDERS)
def test_FR_SKL_every_valid_fixture_passes_and_every_invalid_one_fails(repo_root, registry, folder):
    valid, invalid = list_fixtures(repo_root, folder, "valid"), list_fixtures(repo_root, folder, "invalid")
    assert valid and invalid
    assert all(not errors_for(_ref(folder), load_json(p), registry) for p in valid)
    assert all(errors_for(_ref(folder), load_json(p), registry) for p in invalid), "each invalid case breaks a rule"


def test_FR_SKL_01_a_taught_skill_is_a_sibling_and_skill_yaml_is_unchanged(repo_root):
    taught, skill = load_schema(repo_root, "taught_skill"), load_schema(repo_root, "skill")
    assert (taught["title"], taught["x-version"], taught["additionalProperties"]) == ("TaughtSkill", "1.0.0", False)
    assert {"status", "owner", "captured", "plan"}.isdisjoint(skill["properties"]), "skill.yaml stays expert-signed"
    assert set(taught["$defs"]["method"]["enum"]) == {"describe", "upload", "guided", "record"}
    assert taught["$defs"]["pinned"]["required"] == ["artifact_id", "version"]
    assert set(taught["$defs"]["pinned"]["properties"]) == {"artifact_id", "version"}, "no label, no file name"


@pytest.mark.parametrize("verb", MUST_ASK)
def test_FR_SKL_02_a_send_post_pay_delete_share_or_book_step_always_asks(repo_root, registry, verb):
    record = load_json(repo_root / "contracts/fixtures/taught_skill/valid/learning_team_schedule_record.json")
    step = {"text": "Do it", "tool": "gmail", "action": "send_email", "verb": verb, "ask_first": True}
    for ask_first, must_ask, ok in ((True, True, True), (False, True, False), (True, False, False)):
        record["plan"] = [{**step, "ask_first": ask_first, "must_ask": must_ask}]
        assert bool(errors_for({"$ref": ROOT}, record, registry)) is not ok, (verb, ask_first, must_ask)
    record["plan"] = [
        {**step, "tool": "google_drive", "action": "save_file", "verb": "write", "ask_first": False, "must_ask": False}
    ]
    assert not errors_for({"$ref": ROOT}, record, registry), "the person's switch works on other steps"


@pytest.mark.parametrize("count", [1, 2])
def test_FR_SKL_03_a_try_run_never_records_a_side_effect(repo_root, registry, count):
    result = load_json(repo_root / "contracts/fixtures/taught_skill.try_run_result/valid/completed_one_skipped.json")
    event = load_json(repo_root / "contracts/fixtures/events/valid/skill.try_run.json")
    data_schema = load_schema(repo_root, "events/data/skill.try_run")
    assert not errors_for(_ref("taught_skill.try_run_result"), result, registry)
    assert errors_for(_ref("taught_skill.try_run_result"), {**result, "side_effects": count}, registry)
    assert errors_for(data_schema, {**event["data"], "side_effects": count}, registry)


def test_FR_SKL_04_06_a_draft_never_pauses_and_paused_is_a_flag_not_a_status(repo_root):
    taught = load_schema(repo_root, "taught_skill")
    assert taught["$defs"]["status"]["enum"] == ["draft", "learning", "trusted"]
    assert taught["properties"]["paused"]["type"] == "boolean" and "paused" in taught["required"]


def test_FR_SKL_07_the_helpers_report_holds_counts_only(repo_root):
    defs = load_schema(repo_root, "taught_skill")["$defs"]
    assert set(defs["helpers_report"]["properties"]) == {"org_id", "month", "helpers", "mistakes"}
    assert set(defs["helper"]["properties"]) == {"user", "answers", "fixes"}, "no content, time, speed or mistakes"
    assert all(d["additionalProperties"] is False for d in (defs["helpers_report"], defs["helper"], defs["mistakes"]))


@pytest.mark.parametrize("verb", EVENTS)
def test_FR_SKL_events_are_registered_owner_only_and_carry_no_text(repo_root, verb):
    name = f"skill.{verb}"
    registry_yaml = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    entry = registry_yaml["types"][name]
    assert (entry["family"], entry["verb"], entry["side_effect"], "authz_by" in entry) == ("skill", verb, False, False)
    assert name not in load_schema(repo_root, "event")["if"]["properties"]["type"]["enum"]
    assert TEXT_FIELDS.isdisjoint(load_schema(repo_root, f"events/data/{name}")["properties"]), "ids and counts only"
    event = load_json(repo_root / f"contracts/fixtures/events/valid/{name}.json")
    assert (event["vis"], event["district"], event["level"], event["item"], event["authz"]) == (
        [],
        None,
        None,
        None,
        None,
    )
    assert event["actor"] == event["target"] and event["actor"].startswith("u_")
    assert event["world_id"].startswith("w_desk_")
    sys.path.insert(0, str(repo_root / "scripts"))
    import contracts_codegen
    import contracts_events

    validate = contracts_codegen.validator(contracts_codegen.load_schemas())
    assert (
        contracts_events.event_problems(
            copy.deepcopy(event), contracts_events.load_registry(repo_root / "contracts"), validate
        )
        == []
    )


def test_FR_SKL_01_versions_and_the_capture_video_types(repo_root):
    common = load_schema(repo_root, "common")
    raw = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    assert _version(common) >= (1, 7, 0) and tuple(int(p) for p in raw["version"].split(".")) >= (1, 4, 0)
    assert {"video/webm", "video/mp4"} <= set(common["$defs"]["media_type"]["enum"])
