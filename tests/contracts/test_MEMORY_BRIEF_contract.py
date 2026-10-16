"""MEMORY-BRIEF (ADR-0049): memory_item.schema.json, morning_brief.schema.json and retrieval_chunk.schema.json 1.0.0.

A note is the person's own and never unconfirmed; the prompt block carries notes and a date, never settings text. A
brief is closed, link- and address-free, every section says whether it was read, and without the model there are no
model parts. A chunk keeps uploads, minutes and notes personal and never carries its vector or readers. Rules that
need the principal, stores, reads or prompts (MI, MO, RT) are the builders' api, memory and harness tests.
"""

from __future__ import annotations

import json
import re

import pytest
from _lib import errors_for, list_fixtures, load_json, load_schema

BASE = "https://contracts.tilo.example/"
FOLDERS = (
    "memory_item",
    "memory_item.create",
    "memory_item.update",
    "memory_item.list",
    "memory_item.suggestion",
    "memory_item.prompt_context",
    "morning_brief",
    "morning_brief.settings",
    "morning_brief.settings_update",
    "retrieval_chunk",
    "retrieval_chunk.prompt_block",
    "retrieval_chunk.grounding_ref",
)


def _ref(folder: str) -> dict:
    name, _, key = folder.partition(".")
    return {"$ref": f"{BASE}{name}.schema.json" + (f"#/$defs/{key}" if key else "")}


def _valid(folder: str, doc: object, registry) -> bool:
    return not errors_for(_ref(folder), doc, registry)


def _fixture(repo_root, folder: str, name: str) -> dict:
    return load_json(repo_root / "contracts/fixtures" / folder / "valid" / f"{name}.json")


def _objects(schema: dict) -> list[dict]:
    return [schema] + [d for d in schema["$defs"].values() if d.get("type") == "object"]


@pytest.mark.parametrize("folder", FOLDERS)
def test_MEMORY_BRIEF_FR_WLD_02_every_valid_fixture_passes_and_every_invalid_one_fails(repo_root, registry, folder):
    valid, invalid = list_fixtures(repo_root, folder, "valid"), list_fixtures(repo_root, folder, "invalid")
    assert valid and invalid
    assert [p.name for p in valid if not _valid(folder, load_json(p), registry)] == []
    assert [p.name for p in invalid if _valid(folder, load_json(p), registry)] == []


@pytest.mark.parametrize(
    ("name", "title"),
    [("memory_item", "MemoryItem"), ("morning_brief", "MorningBrief"), ("retrieval_chunk", "RetrievalChunk")],
)
def test_MEMORY_BRIEF_FR_WLD_02_schemas_are_closed_versioned_and_have_no_root_allof(repo_root, name, title):
    schema = load_schema(repo_root, name)
    assert (schema["$id"], schema["title"], schema["x-version"]) == (f"{BASE}{name}.schema.json", title, "1.0.0")
    assert "allOf" not in schema
    assert all(o["additionalProperties"] is False for o in _objects(schema))
    assert set(schema["required"]) == set(schema["properties"])


def test_MEMORY_BRIEF_MI_02_bodies_name_no_server_owned_field_and_there_is_no_unconfirmed_state(repo_root, registry):
    schema = load_schema(repo_root, "memory_item")
    assert set(schema["$defs"]["create"]["properties"]) == {"text", "kind", "source"}
    assert set(schema["$defs"]["update"]["properties"]) == {"text", "kind"}
    assert "confirmed" not in schema["properties"] and schema["$defs"]["source"]["enum"] == ["user", "tilo_suggested"]
    body = _fixture(repo_root, "memory_item.create", "typed_on_the_list")
    for field, value in (("owner", "u_other"), ("org_id", "org_other"), ("id", "mem_x1"), ("confirmed", True)):
        assert not _valid("memory_item.create", {**body, field: value}, registry), field
    assert not _valid("memory_item.update", {}, registry)


@pytest.mark.parametrize(
    "text",
    ["See https://example.com/x", "Notes at example.org/q4", "two\nlines", " leading", "zero​width", "x" * 281],
)
def test_MEMORY_BRIEF_MI_03_a_note_is_one_short_link_free_line(repo_root, registry, text):
    item = _fixture(repo_root, "memory_item", "preference_typed")
    assert not _valid("memory_item", {**item, "text": text}, registry)
    assert not _valid("memory_item.suggestion", {"text": text, "kind": "fact"}, registry)


def test_MEMORY_BRIEF_MI_05_prompt_context_holds_a_date_and_at_most_20_notes_and_no_settings_text(repo_root, registry):
    schema = load_schema(repo_root, "memory_item")
    block = schema["$defs"]["prompt_context"]
    assert set(block["properties"]) == {"v", "today", "items"} and block["properties"]["items"]["maxItems"] == 20
    ctx = _fixture(repo_root, "memory_item.prompt_context", "two_notes")
    for field in ("name", "title", "email", "time_zone", "language"):
        assert not _valid("memory_item.prompt_context", {**ctx, field: "x"}, registry), field


def test_MEMORY_BRIEF_MO_07_without_the_model_there_are_no_model_parts(repo_root, registry):
    brief = _fixture(repo_root, "morning_brief", "full_day_model_used")
    for model in ("skipped", "failed", "flagged"):
        unsorted = {
            **brief,
            "model": model,
            "mail_needing_reply": {**brief["mail_needing_reply"], "status": "unsorted"},
        }
        assert not _valid("morning_brief", unsorted, registry), f"{model} with suggestions"
        bare = {**unsorted, "suggestions": [], "todo_suggestions": []}
        assert _valid("morning_brief", bare, registry), model
        assert not _valid("morning_brief", {**bare, "mail_needing_reply": brief["mail_needing_reply"]}, registry)


def test_MEMORY_BRIEF_MO_11_a_brief_names_no_recipient_address_body_or_link_field(repo_root, registry):
    schema = load_schema(repo_root, "morning_brief")
    names = set(re.findall(r'"([a-z_]+)":', json.dumps(schema["properties"]) + json.dumps(schema["$defs"])))
    assert not names & {"recipients", "to", "email", "address", "url", "link", "body", "snippet", "from", "send_at"}
    brief = _fixture(repo_root, "morning_brief", "full_day_model_used")
    assert not _valid("morning_brief", {**brief, "recipients": ["a@example.com"]}, registry)
    mail = brief["mail_needing_reply"]["items"][0]
    for field, value in (("from_name", "priya@example.com"), ("subject", "Pay at https://example.org")):
        doc = {**brief, "mail_needing_reply": {"status": "ok", "items": [{**mail, field: value}]}}
        assert not _valid("morning_brief", doc, registry), field


@pytest.mark.parametrize("status", ["not_connected", "unavailable"])
def test_MEMORY_BRIEF_MO_12_a_section_that_was_not_read_carries_no_items(repo_root, registry, status):
    brief = _fixture(repo_root, "morning_brief", "full_day_model_used")
    meetings = {"status": status, "items": brief["meetings"]["items"]}
    assert not _valid("morning_brief", {**brief, "meetings": meetings}, registry)
    assert _valid("morning_brief", {**brief, "meetings": {"status": status, "items": []}}, registry)


def test_MEMORY_BRIEF_MO_02_settings_write_names_no_server_owned_field(repo_root, registry):
    schema = load_schema(repo_root, "morning_brief")
    assert set(schema["$defs"]["settings_update"]["properties"]) == {"enabled", "time", "time_zone", "email_copy"}
    body = _fixture(repo_root, "morning_brief.settings_update", "turn_on_in_app_only")
    for field, value in (("owner_id", "u_x"), ("email_rule_ready", True), ("updated_at", "2026-10-16T00:00:00.000Z")):
        assert not _valid("morning_brief.settings_update", {**body, field: value}, registry), field


@pytest.mark.parametrize("kind", ["upload", "minutes", "memory_item"])
def test_MEMORY_BRIEF_RT_02_uploads_minutes_and_notes_are_never_team_chunks(repo_root, registry, kind):
    chunk = _fixture(
        repo_root,
        "retrieval_chunk",
        {"upload": "upload_with_tabs_and_line_breaks", "minutes": "own_minutes", "memory_item": "own_note"}[kind],
    )
    assert chunk["source"]["kind"] == kind and _valid("retrieval_chunk", chunk, registry)
    assert not _valid("retrieval_chunk", {**chunk, "team_id": "tm_ops"}, registry)


def test_MEMORY_BRIEF_RT_03_a_chunk_carries_no_vector_or_reader_list_and_its_id_binds_its_kind(repo_root, registry):
    chunk = _fixture(repo_root, "retrieval_chunk", "own_note")
    for field, value in (("embedding", [0.1]), ("readers", ["u_alex"]), ("score", 0.9)):
        assert not _valid("retrieval_chunk", {**chunk, field: value}, registry), field
    for kind, ident in (("memory_item", "art_x1"), ("pin", "mem_x1"), ("deliverable", "pb_x1"), ("minutes", "art_x1")):
        version = 1 if kind in ("deliverable", "minutes") else None
        source = {"kind": kind, "id": ident, "version": version}
        assert not _valid("retrieval_chunk", {**chunk, "source": source}, registry), (kind, ident)
    team = _fixture(repo_root, "retrieval_chunk", "deliverable_of_a_team_shared_world")
    assert not _valid("retrieval_chunk", {**team, "world_id": None}, registry)


@pytest.mark.parametrize(
    ("name", "prefix", "count"), [("memory_item", "MI", 10), ("morning_brief", "MO", 12), ("retrieval_chunk", "RT", 10)]
)
def test_MEMORY_BRIEF_rules_files_number_their_rules(repo_root, name, prefix, count):
    text = (repo_root / "contracts" / f"{name}.rules.md").read_text(encoding="utf-8")
    assert re.findall(r"^\| ([A-Z]{2}-\d\d) \|", text, flags=re.M) == [f"{prefix}-{n:02d}" for n in range(1, count + 1)]


def test_MEMORY_BRIEF_MI_06_memory_saved_has_a_desk_world_fixture(repo_root):
    event = load_json(repo_root / "contracts/fixtures/events/valid/memory.saved--desk_owner_only.json")
    assert (event["type"], event["vis"], event["district"], event["data"]) == (
        "memory.saved",
        [],
        None,
        {"layer": "preferences", "item_count": 1},
    )
    assert event["actor"] == event["target"]
