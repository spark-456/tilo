"""ADR-0050 (16 Oct 2026, the owner's approval): the website deliverable and where a deliverable is made.

common 1.8.0 (`website`, `text/html`, `make_with`), artifact 1.2.0 (a writer unit's HTML, at most 512 KiB, never an
upload, fetch or render), plan 1.2.0 (`make_choice`, `make_option`), makers 1.0.0 (config/makers.yaml),
mcp_tools 1.1.0 (no HTML text over MCP), artifact.created 1.2.0, artifact.delivered 1.1.0 and the new
plan.maker_chosen (registry 1.6.0). All additive: every older fixture and shipped config stays valid."""

from __future__ import annotations

import re

import pytest
import yaml
from _lib import errors_for, load_json, load_schema

FIXTURES = "contracts/fixtures"
NEW_INVALID = {
    "common": (
        *("media_type_image_svg", "make_with_bare_connector_id", "make_with_upper_case_connector"),
        *("make_with_url", "make_with_mcp_without_tool", "make_with_native_with_id"),
    ),
    "artifact": ("unit_html_over_512_kb", "render_origin_with_html", "fetch_origin_with_html", "media_type_text_html"),
    "plan.make_choice": (
        *("native_suggested", "needs_setup_suggested", "suggested_without_note", "needs_setup_without_note"),
        *("native_needs_setup", "ready_option_with_note", "one_option_only", "selected_is_a_label"),
        *("deliverable_ten", "status_unknown"),
    ),
    "makers": (
        *("partner_native", "format_unknown", "partners_empty", "need_upper_case", "need_five_words"),
        *("max_native_pages_zero", "preselect_missing", "unknown_key", "action_not_an_action_type", "v_not_1_0"),
    ),
    "mcp_tools.read_artifact_out": ("html_media_type", "pdf_with_text"),
}
NEW_VALID = {
    "common": ("deliverable_format_website", "media_type_text_html", "make_with_native", "make_with_mcp_tool"),
    "artifact": ("unit_website_html_at_cap",),
    "plan.make_choice": ("website_large_lovable_suggested", "website_small_native", "pptx_canva_needs_setup"),
    "makers": ("three_formats", "mcp_partner_native_first"),
    "mcp_tools.read_artifact_out": ("html_withheld",),
}
MINIMUM = {"common": (1, 8, 0), "artifact": (1, 2, 0), "plan": (1, 2, 0), "mcp_tools": (1, 1, 0), "makers": (1, 0, 0)}


def _ref(folder):
    name, _, key = folder.partition(".")
    return {"$ref": f"https://contracts.tilo.example/{name}.schema.json" + (f"#/$defs/{key}" if key else "")}


def _version(schema):
    return tuple(int(p) for p in schema["x-version"].split("."))


@pytest.mark.parametrize("name", MINIMUM)
def test_ADR_0050_bumps_are_additive_on_major_1(repo_root, name):
    version = _version(load_schema(repo_root, name))
    assert version >= MINIMUM[name] and version[0] == 1


@pytest.mark.parametrize("folder,name", [(f, n) for f, names in NEW_VALID.items() for n in names])
def test_FR_AGT_16_FR_CON_16_valid_fixtures_pass(repo_root, registry, folder, name):
    assert not errors_for(_ref(folder), load_json(repo_root / f"{FIXTURES}/{folder}/valid/{name}.json"), registry)


@pytest.mark.parametrize("folder,name", [(f, n) for f, names in NEW_INVALID.items() for n in names])
def test_FR_AGT_16_FR_CON_16_each_rule_has_an_invalid_fixture(repo_root, registry, folder, name):
    assert errors_for(_ref(folder), load_json(repo_root / f"{FIXTURES}/{folder}/invalid/{name}.json"), registry)


def test_FR_AGT_16_website_is_a_format_and_html_only_a_writer_units_output(repo_root, registry):
    common = load_schema(repo_root, "common")
    assert "website" in common["$defs"]["deliverable_format"]["enum"]
    assert "text/html" in common["$defs"]["media_type"]["enum"]
    assert "image/svg+xml" not in common["$defs"]["media_type"]["enum"], "SVG stays closed"
    record = load_json(repo_root / f"{FIXTURES}/artifact/valid/unit_website_html_at_cap.json")
    upload = {**record, "origin": {"kind": "upload", "unit": None, "agent": None}, "sources": []}
    restore = {**record, "origin": {"kind": "restore", "unit": None, "agent": None}, "idempotency_key": None}
    restore["parents"] = [record["artifact"]]
    assert errors_for(_ref("artifact"), {**upload, "idempotency_key": None}, registry), "AR-10: no HTML upload"
    assert not errors_for(_ref("artifact"), restore, registry), "a restore keeps a stored website's type"
    assert errors_for(_ref("artifact"), {**restore, "size_bytes": 524_289}, registry), "the cap holds for a restore"


def test_FR_CON_16_make_with_names_native_a_connector_or_an_mcp_tool(repo_root, registry):
    good = ("native", "connector:lovable", "connector:canva", "mcp:notes_hub:create_page", "mcp:hub:tool.v2-x")
    bad = ("Native", "connector:", "connector:l", "mcp:hub:", "mcp::tool", "connector:lovable\n", " native")
    for value in good:
        assert not errors_for(_ref("common"), {"make_with": value}, registry), value
    for value in bad:
        assert errors_for(_ref("common"), {"make_with": value}, registry), repr(value)


def test_FR_CON_16_FR_CON_19_shipped_makers_config(repo_root, registry):
    config = yaml.safe_load((repo_root / "config/makers.yaml").read_text(encoding="utf-8"))
    assert not errors_for(_ref("makers"), config, registry)
    partners = {fmt: [p["make_with"] for p in o["partners"]] for fmt, o in config["formats"].items()}
    assert partners == {"website": ["connector:lovable"], "pptx": ["connector:canva"], "pdf": ["connector:canva"]}
    actions = {p["make_with"]: p["action"] for o in config["formats"].values() for p in o["partners"]}
    assert actions == {"connector:lovable": "build_handoff", "connector:canva": "create_design"}
    connectors = yaml.safe_load((repo_root / "config/connectors.yaml").read_text(encoding="utf-8"))
    canva = yaml.safe_load((repo_root / "config/canva.yaml").read_text(encoding="utf-8"))
    declared = {c["id"]: c for c in [*connectors, *canva]}
    for make_with, action in actions.items():
        entry = declared[make_with.removeprefix("connector:")]
        found = [a for a in entry["actions"] if a["id"] == action]
        assert found and found[0]["risk_tier"] == "T3" and found[0]["gate_type"] != "none", "MK-07: a pick is no grant"
    assert config["large_site"]["max_native_pages"] >= 1 and config["preselect_suggested"] is True


def test_FR_CON_16_plan_maker_chosen_is_registered_and_not_a_side_effect(repo_root):
    registry_doc = yaml.safe_load((repo_root / "contracts/events/registry.yaml").read_text(encoding="utf-8"))
    assert _version({"x-version": str(registry_doc["version"])}) >= (1, 6, 0)
    entry = registry_doc["types"]["plan.maker_chosen"]
    assert (entry["family"], entry["side_effect"], entry["pillar"]) == ("plan", False, "P1")
    side_effect_list = load_schema(repo_root, "event")["if"]["properties"]["type"]["enum"]
    assert "plan.maker_chosen" not in side_effect_list


def test_FR_CON_16_a_partner_delivery_names_its_outbox_entry(repo_root, registry):
    schema = load_json(repo_root / "contracts/events/data/artifact.delivered.schema.json")
    ref = {"artifact": {"artifact_id": "art_site", "version": 1}}
    ulid = "01JB5VQ00000000000000WEB06"
    cases = {
        ("website", None, "native"): True,
        ("website", ulid, "connector:lovable"): True,
        ("pptx", ulid, "connector:canva"): True,
        ("pptx", None, None): True,  # 1.0.0 shape
        ("website", None, None): False,
        ("website", ulid, "native"): False,
        ("pdf", None, "connector:canva"): False,
    }
    for (fmt, outbox, make_with), ok in cases.items():
        data = {**ref, "format": fmt, "outbox_id": outbox} | ({"make_with": make_with} if make_with else {})
        assert (not errors_for(schema, data, registry)) is ok, (fmt, outbox, make_with)


def test_FR_AGT_16_rules_files_hold_every_rule_id(repo_root):
    texts = {name: (repo_root / f"contracts/{name}.rules.md").read_text(encoding="utf-8") for name in (
        "website", "makers", "artifact")}  # fmt: skip
    assert re.findall(r"^\| (WS-\d\d) ", texts["website"], re.M) == [f"WS-{i:02d}" for i in range(1, 16)]
    assert re.findall(r"^\| (MK-\d\d) ", texts["makers"], re.M) == [f"MK-{i:02d}" for i in range(1, 9)]
    assert "| AR-10 |" in texts["artifact"]
    assert "sandbox allow-scripts" in texts["website"] and "allow-same-origin" in texts["website"]
    assert "connect-src 'none'" in texts["website"] and "attachment" in texts["website"]
