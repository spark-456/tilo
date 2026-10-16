"""ADR-0051 (16 Oct 2026, the owner's request): teach a skill three ways, @ mentions, an agentic browser.

browser 1.0.0 (config/browser.yaml shape, the closed action set, session and control bodies), mentions 1.0.0 (the @
picker page and typed refs), registry 1.7.0 (browser.started, .acted, .controlled, .stopped), artifact 1.3.0 (origin
browser: a masked PNG frame) and taught_skill 1.2.0 (inputs, hosts). All additive on major 1."""

from __future__ import annotations

import re

import pytest
import yaml
from _lib import errors_for, load_json, load_schema

FIXTURES = "contracts/fixtures"
MINIMUM = {"browser": (1, 0, 0), "mentions": (1, 0, 0), "artifact": (1, 3, 0), "taught_skill": (1, 2, 0)}
BROWSER_EVENTS = ("browser.started", "browser.acted", "browser.controlled", "browser.stopped")


def _ref(folder):
    name, _, key = folder.partition(".")
    return {"$ref": f"https://contracts.tilo.example/{name}.schema.json" + (f"#/$defs/{key}" if key else "")}


def _version(text):
    return tuple(int(p) for p in str(text).split("."))


@pytest.mark.parametrize("name", MINIMUM)
def test_ADR_0051_bumps_are_additive_on_major_1(repo_root, name):
    version = _version(load_schema(repo_root, name)["x-version"])
    assert version >= MINIMUM[name] and version[0] == 1


def test_FR_CON_07_browser_ceilings_cannot_be_raised_by_config(repo_root, registry):
    props = load_schema(repo_root, "browser")["properties"]
    assert props["max_sessions_per_world"]["maximum"] == 3, "PRD 12.3: at most 3 sessions per world"
    assert props["max_steps"]["maximum"] == 60 and props["model_frames"]["maximum"] == 3
    example = load_json(repo_root / f"{FIXTURES}/browser/valid/shipped_defaults_example.json")
    for key, value in (("max_sessions_per_world", 4), ("max_steps", 61), ("allow_any_host", True)):
        assert errors_for(_ref("browser"), {**example, key: value}, registry), key


def test_FR_CON_07_the_model_can_only_propose_the_closed_action_set(repo_root, registry):
    defs = load_schema(repo_root, "browser")["$defs"]
    kinds = defs["action_kind"]["enum"]
    variants = [defs[r["$ref"].split("/")[-1]]["properties"]["kind"]["const"] for r in defs["action"]["oneOf"]]
    assert variants == kinds and not {"download", "upload", "eval", "select", "script"} & set(kinds)
    for name in ("click", "type", "navigate", "done"):
        assert defs[f"{name}_action"]["additionalProperties"] is False
    bad = ("http://a.example.com/", "https://u@a.example.com/", "https://a.example.com\\@b.example.org/",
           "https://a.example.com/\n", "file:///etc/passwd", "javascript:alert(1)")  # fmt: skip
    for url in bad:
        assert errors_for(_ref("browser.action"), {"kind": "navigate", "url": url}, registry), repr(url)


def test_FR_CON_07_hosts_are_host_names_never_urls(repo_root, registry):
    good = ("shop.example.com", "xn--bcher-kva.example", "a-b.example.org")
    bad = ("Shop.example.com", "shop.example.com:443", "https://shop.example.com", "localhost", "shop.example.com\n")
    for host in good:
        assert not errors_for(_ref("browser.host"), host, registry), host
    for host in bad:
        assert errors_for(_ref("browser.host"), host, registry), repr(host)
    assert not errors_for(_ref("browser.allow_host"), "*.example.org", registry)
    assert errors_for(_ref("browser.allow_host"), "*", registry)


def test_FR_CON_07_click_and_type_name_the_inspected_element(repo_root, registry):
    act = load_json(repo_root / f"{FIXTURES}/browser.act_request/valid/click_with_digest.json")
    assert errors_for(_ref("browser.act_request"), {**act, "digest": None}, registry), "BR-03"
    navigate = {**act, "action": {"kind": "navigate", "url": "https://shop.example.com/"}, "digest": None}
    assert not errors_for(_ref("browser.act_request"), navigate, registry)


def test_FR_CON_07_browser_events_are_registered_and_never_side_effects(repo_root):
    registry_doc = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    assert _version(registry_doc["version"]) >= (1, 7, 0)
    families = load_schema(repo_root, "events/registry")["$defs"]["family"]["enum"]
    assert "browser" in families
    side_effect_list = load_schema(repo_root, "event")["if"]["properties"]["type"]["enum"]
    for name in BROWSER_EVENTS:
        entry = registry_doc["types"][name]
        assert entry["family"] == "browser" and entry["side_effect"] is False, name
        assert name not in side_effect_list
        assert (repo_root / "contracts" / entry["fixture"]).is_file()


@pytest.mark.parametrize("name", BROWSER_EVENTS)
def test_FR_CON_07_browser_events_carry_no_url_text_or_query(repo_root, name):
    data = load_json(repo_root / f"contracts/events/data/{name}.schema.json")
    assert not {"url", "text", "query", "title", "summary", "page_text"} & set(data["properties"]), "BR-13"


def test_FR_CON_07_a_browser_frame_is_a_png_made_for_a_unit(repo_root, registry):
    frame = load_json(repo_root / f"{FIXTURES}/artifact/valid/browser_frame_png.json")
    assert not errors_for(_ref("artifact"), frame, registry)
    for media in ("image/jpeg", "text/markdown", "text/html", "application/pdf"):
        assert errors_for(_ref("artifact"), {**frame, "media_type": media}, registry), media
    no_unit = {**frame, "origin": {"kind": "browser", "unit": None, "agent": None}}
    assert errors_for(_ref("artifact"), no_unit, registry), "AR-11: the store sets unit and agent"


def test_FR_PA_11_a_mention_ref_carries_ids_never_content(repo_root, registry):
    defs = load_schema(repo_root, "mentions")["$defs"]
    kinds = defs["kind"]["enum"]
    variants = [defs[r["$ref"].split("/")[-1]] for r in defs["ref"]["oneOf"]]
    assert [v["properties"]["kind"]["const"] for v in variants] == kinds
    for variant in variants:
        assert variant["additionalProperties"] is False
        assert set(variant["properties"]) <= {"kind", "id", "version"}, "MN-01, MN-08"
    assert defs["refs"]["maxItems"] == 10 and defs["refs"]["uniqueItems"] is True
    assert set(defs["ref_error"]["properties"]) == {"error", "index"}, "MN-02: the refusal names nothing"
    file_ref = {"kind": "file", "id": "art_triage_list"}
    assert errors_for(_ref("mentions.ref"), file_ref, registry), "a file pins its version"


def test_FR_SKL_02_a_browse_step_needs_the_hosts_the_person_kept(repo_root, registry):
    skill = load_json(repo_root / f"{FIXTURES}/taught_skill/valid/learning_browse_step_with_hosts_and_inputs.json")
    assert not errors_for(_ref("taught_skill"), skill, registry)
    without = {k: v for k, v in skill.items() if k != "hosts"}
    assert errors_for(_ref("taught_skill"), without, registry), "TS-18"
    no_browse = {**without, "plan": [s for s in skill["plan"] if s["action"] != "browse_web"]}
    assert not errors_for(_ref("taught_skill"), no_browse, registry), "hosts stay optional otherwise"
    for older in ("draft_describe_just_me", "learning_team_schedule_record", "trusted_paused_event_trigger_upload"):
        assert not errors_for(
            _ref("taught_skill"), load_json(repo_root / f"{FIXTURES}/taught_skill/valid/{older}.json"), registry
        )


def test_FR_SKL_01_rules_files_hold_every_new_rule_id(repo_root):
    def ids(name, prefix):
        text = (repo_root / f"contracts/{name}.rules.md").read_text(encoding="utf-8")
        return re.findall(rf"^\| ({prefix}-\d\d) ", text, re.M)

    assert ids("browser", "BR") == [f"BR-{i:02d}" for i in range(1, 15)]
    assert ids("mentions", "MN") == [f"MN-{i:02d}" for i in range(1, 11)]
    assert ids("taught_skill", "TS")[-4:] == ["TS-18", "TS-19", "TS-20", "TS-21"]
    assert "AR-11" in ids("artifact", "AR")
