"""FR-MEM-12 and FR-CON-15 (docs/prd-supplement-2026-10-05.md), ADR-0018 ticket T1 (BQ-256 approved).

The contract half of the artifact store: contracts/artifact.schema.json (ArtifactVersion 1.0.0 and its
manifest revision), common.schema.json `media_type` (common 1.1.0, now merged into 1.2.0), artifact.created
data 1.1.0 (optional content_sha256, media_type and size_bytes, all or none) and event rule EV-15. Caps are BQ-257's
(2,000,000 bytes text and structured, 50,000,000 a file, 10 outputs per unit); `redacted` is BQ-258's.
"""

from __future__ import annotations

import json
import re
import sys

import pytest
from _lib import errors_for, load_json, load_schema

OOXML = "application/vnd.openxmlformats-officedocument."
MEDIA_TYPES = {"text/markdown", "text/csv", "application/json", "application/pdf", "image/png", "image/jpeg"}
MEDIA_TYPES |= {OOXML + t for t in ("presentationml.presentation", "wordprocessingml.document", "spreadsheetml.sheet")}
REQUIRED = {"v", "artifact", "org_id", "world_id", "run_id", "owner", "media_type", "size_bytes", "content_sha256"}
REQUIRED |= {"parents", "origin", "sources", "screening", "screened_at", "redacted", "idempotency_key", "created_at"}
SHA = "0123456789abcdef" * 4
STORED = {"artifact": {"artifact_id": "art_report", "version": 1}, "content_sha256": SHA}
STORED |= {"media_type": "text/markdown", "size_bytes": 1200}
# One invalid fixture per rule the schema holds (ADR-0018 4, BQ-257, BQ-258).
INVALID = {
    "artifact": (
        *("size_bytes_zero", "file_over_50_mb", "markdown_over_2_mb", "csv_over_2_mb", "json_over_2_mb"),
        *("media_type_text_html", "media_type_svg", "content_sha256_upper_case", "blob_path_field"),
        *("org_id_with_slash", "unit_output_without_idempotency_key", "upload_with_idempotency_key"),
        *("restore_with_idempotency_key", "idempotency_key_eleventh_output", "unit_origin_without_unit"),
        *("upload_origin_with_agent", "two_parents", "screening_unknown", "redacted_missing", "source_with_text"),
        # Security r1 on #366: a model never makes a file, render makes only files, an upload has no archive
        # sources, and `clean` or `flagged` needs the SafetyProvider verdict's time (AR-07).
        *("unit_origin_with_pdf", "unit_origin_with_pptx", "render_origin_with_markdown", "upload_with_sources"),
        *("upload_clean_without_screen_record", "unscreened_with_a_verdict_time"),
    ),
    "artifact.manifest_revision": (
        *("stage_unknown", "n_zero", "manifest_without_content_sha256", "reviewed_without_cause"),
        "sent_without_cause",
    ),
    "common": ("media_type_text_html",),
}
INVALID_STREAMS = (
    *("ev15_created_names_version_2", "ev15_reviewed_version_never_recorded", "ev15_delivered_before_created"),
    *("ev15_delivered_other_artifact", "ev15_versioned_previous_never_recorded"),
    *("ev15_rolled_back_restored_never_recorded", "ev15_created_twice", "ev15_versioned_skips_a_version"),
    "ev15_rolled_back_onto_a_recorded_version",
)


def _ref(folder):
    name, _, key = folder.partition(".")
    return {"$ref": f"https://contracts.tilo.example/{name}.schema.json" + (f"#/$defs/{key}" if key else "")}


def _scripts(repo_root):
    sys.path.insert(0, str(repo_root / "scripts"))
    import contracts_codegen
    import contracts_events

    return contracts_codegen.validator(contracts_codegen.load_schemas()), contracts_events


def test_FR_MEM_12_artifact_schema_is_artifact_version_1_0_0(repo_root):
    schema = load_schema(repo_root, "artifact")
    assert schema["$id"] == "https://contracts.tilo.example/artifact.schema.json"
    assert (schema["x-version"], schema["title"]) == ("1.0.0", "ArtifactVersion")
    assert set(schema["required"]) == REQUIRED == set(schema["properties"]), "ADR-0018 4: no blob path field"
    assert schema["additionalProperties"] is False
    stages = set(schema["$defs"]["manifest_revision"]["properties"]["stage"]["enum"])
    assert stages == {"created", "reviewed", "sent", "exported"}


def test_FR_MEM_12_media_type_is_a_closed_enum_of_nine(repo_root):
    common = load_schema(repo_root, "common")
    major, minor, _patch = (int(p) for p in common["x-version"].split("."))
    assert (major, minor) >= (1, 2), "an added $defs entry is a minor bump (ADR-0002); 1.2.0 merges both 1.1.0s"
    enum = common["$defs"]["media_type"]["enum"]
    assert set(enum) == MEDIA_TYPES and len(enum) == 9 and "media_type" in common["properties"]


def test_FR_MEM_12_valid_records_cover_every_origin_and_both_caps(repo_root, registry):
    records = [load_json(p) for p in sorted((repo_root / "contracts/fixtures/artifact/valid").glob("*.json"))]
    assert all(not errors_for(_ref("artifact"), record, registry) for record in records)
    assert {r["origin"]["kind"] for r in records} == {"unit", "render", "upload", "restore"}
    caps = {("application/json", 2_000_000), ("application/pdf", 50_000_000)}
    assert {(r["media_type"], r["size_bytes"]) for r in records} >= caps, "the text and file caps are inclusive"


@pytest.mark.parametrize("folder,name", [(f, n) for f, names in INVALID.items() for n in names])
def test_FR_MEM_12_each_rule_has_an_invalid_fixture_that_fails(repo_root, registry, folder, name):
    fixture = load_json(repo_root / f"contracts/fixtures/{folder}/invalid/{name}.json")
    assert errors_for(_ref(folder), fixture, registry), f"{folder}/invalid/{name}.json must fail"


def _foreign_sources(record):
    """AR-03 reference check: a unit or render output's sources are records of its own run (the run in the
    Scope). A restore copies the copied version's sources, and an upload has none (schema)."""
    if record["origin"]["kind"] not in ("unit", "render"):
        return []
    return [s["archive_ref"] for s in record["sources"] if s["archive_ref"].split("/", 1)[0] != record["run_id"]]


def test_FR_MEM_12_AR_03_sources_come_from_the_records_own_run(repo_root, registry):
    fixtures = repo_root / "contracts/fixtures/artifact"
    assert all(_foreign_sources(load_json(p)) == [] for p in (fixtures / "valid").glob("*.json"))
    invalid = sorted((fixtures / "crossref/invalid").glob("ar03_*.json"))
    assert invalid, "AR-03 needs an invalid cross-reference case"
    for path in invalid:
        record = load_json(path)
        assert not errors_for(_ref("artifact"), record, registry), f"{path.name} passes the schema"
        assert _foreign_sources(record), f"{path.name} must break AR-03"


def test_FR_MEM_12_artifact_created_data_is_1_1_0_and_additive(repo_root, registry):
    schema = load_json(repo_root / "contracts/events/data/artifact.created.schema.json")
    assert (schema["x-version"], schema["required"]) == ("1.1.0", ["artifact"])
    assert not errors_for(schema, {"artifact": STORED["artifact"]}, registry), "1.0.0 events stay valid"
    assert not errors_for(schema, STORED, registry)
    for change in ({"media_type": "text/html"}, {"size_bytes": 0}, {"size_bytes": 2_000_001}):
        assert errors_for(schema, STORED | change, registry), change
    for missing in ("content_sha256", "media_type", "size_bytes"):
        partial = {k: v for k, v in STORED.items() if k != missing}
        assert errors_for(schema, partial, registry), f"all three or none, {missing} missing"


def _check(repo_root, path):
    validate, events = _scripts(repo_root)
    stream = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    registry = events.load_registry(repo_root / "contracts")
    assert [p for e in stream for p in events.event_problems(e, registry, validate)] == [], "passes the schemas"
    layout = load_json(repo_root / "contracts/fixtures/layout/valid/village_basic.json")
    return stream, events.stream_problems(stream, events.layout_ids(layout))


def test_FR_MEM_12_EV_15_versions_restore_review_and_delivery_stream_is_valid(repo_root):
    stream, problems = _check(repo_root, repo_root / "contracts/fixtures/streams/artifact-versions.jsonl")
    assert problems == []
    types = {f"artifact.{v}" for v in ("created", "versioned", "rolled_back", "reviewed", "delivered")}
    assert {e["type"] for e in stream} == types
    assert {"content_sha256", "media_type", "size_bytes"} <= stream[0]["data"].keys(), "a stored 1.1.0 created"


@pytest.mark.parametrize("name", INVALID_STREAMS)
def test_FR_CON_15_EV_15_delivery_names_only_what_the_world_created(repo_root, name):
    _, problems = _check(repo_root, repo_root / f"contracts/fixtures/streams/invalid/{name}.jsonl")
    assert problems and all(p.startswith("EV-15") for p in problems), problems


def test_FR_MEM_12_EV_15_and_AR_rules_are_written_down(repo_root):
    assert "| EV-15 |" in (repo_root / "contracts/event.rules.md").read_text(encoding="utf-8")
    rules = (repo_root / "contracts/artifact.rules.md").read_text(encoding="utf-8")
    assert all(f"| AR-0{n} |" in rules for n in range(1, 9))
    ar07 = next(line for line in rules.splitlines() if line.startswith("| AR-07 |"))
    assert all(w in ar07 for w in ("SafetyProvider", "unscreened", "safety_flag", "policy engine")), "security r1"


def test_FR_MEM_12_generated_types(repo_root):
    python = (repo_root / "packages/contracts-py/src/tilo_contracts/__init__.py").read_text(encoding="utf-8")
    typescript = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    for name in ("ArtifactVersion", "ArtifactVersionManifestRevision", "ArtifactVersionOrigin"):
        assert re.search(rf"^class {name}\(", python, re.M) and f"export interface {name} " in typescript
    assert re.search(r"^type MediaType = Literal\[", python, re.M) and "export type MediaType =" in typescript
    created = typescript.split("export interface ArtifactCreatedData {", 1)[1].split("}", 1)[0]
    assert all(f"{field}?:" in created for field in ("content_sha256", "media_type", "size_bytes"))
