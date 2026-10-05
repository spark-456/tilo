"""FR-MEM-12 and FR-CON-15 (docs/prd-supplement-2026-10-05.md), ADR-0018 ticket T1 (BQ-256 approved).

The contract half of the artifact store: contracts/artifact.schema.json (ArtifactVersion 1.0.0 and its
manifest revision), common.schema.json `media_type` (common 1.1.0), artifact.created data 1.1.0 (optional
content_sha256, media_type and size_bytes, all or none) and event rule EV-15. Caps are BQ-257's
(2,000,000 bytes text and structured, 50,000,000 a file, 10 outputs per unit); `redacted` is BQ-258's.
"""

from __future__ import annotations

import copy
import json
import re
import sys

import pytest
from _lib import errors_for, load_json, load_schema

MEDIA_TYPES = {
    "text/markdown",
    "text/csv",
    "application/json",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpeg",
}
TEXT_TYPES = ("text/markdown", "text/csv", "application/json")
REQUIRED = {"v", "artifact", "org_id", "world_id", "run_id", "owner", "media_type", "size_bytes", "content_sha256"}
REQUIRED |= {"parents", "origin", "sources", "screening", "redacted", "idempotency_key", "created_at"}
SHA = "0123456789abcdef" * 4
UNIT = {"kind": "unit", "unit": "U2", "agent": "A_s1"}
UPLOAD = {"kind": "upload", "unit": None, "agent": None}
RECORD = {
    "v": "1.0",
    "artifact": {"artifact_id": "art_report", "version": 1, "label": "Market report"},
    "org_id": "org_example",
    "world_id": "w_example",
    "run_id": "r_example_1",
    "owner": "u_owner",
    "media_type": "text/markdown",
    "size_bytes": 1200,
    "content_sha256": SHA,
    "parents": [],
    "origin": UNIT,
    "sources": [{"id": "src_market", "archive_ref": "r_example_1/7"}],
    "screening": "clean",
    "redacted": False,
    "idempotency_key": "r_example_1:U2:1:0",
    "created_at": "2026-10-05T09:30:00.000Z",
}
STORED = {"artifact": {"artifact_id": "art_report", "version": 1}, "content_sha256": SHA}
STORED |= {"media_type": "text/markdown", "size_bytes": 1200}


def _record(**changes):
    return copy.deepcopy(RECORD) | changes


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


def test_FR_MEM_12_media_type_is_a_closed_enum_of_nine(repo_root):
    common = load_schema(repo_root, "common")
    assert common["x-version"] == "1.1.0", "an added $defs entry is a minor bump (ADR-0002)"
    assert set(common["$defs"]["media_type"]["enum"]) == MEDIA_TYPES
    assert len(common["$defs"]["media_type"]["enum"]) == 9 and "media_type" in common["properties"]


@pytest.mark.parametrize(
    "record",
    [
        _record(),
        _record(
            media_type="application/pdf", size_bytes=50_000_000, origin={"kind": "render", "unit": "U2", "agent": None}
        ),
        *(_record(media_type=t, size_bytes=2_000_000) for t in TEXT_TYPES),
        _record(origin=UPLOAD, idempotency_key=None, media_type="image/png", sources=[]),
        _record(
            artifact={"artifact_id": "art_report", "version": 3},
            parents=[{"artifact_id": "art_report", "version": 1}],
            origin={"kind": "restore", "unit": None, "agent": None},
            idempotency_key=None,
            redacted=True,
        ),
    ],
)
def test_FR_MEM_12_artifact_records_that_validate(repo_root, registry, record):
    assert not errors_for(load_schema(repo_root, "artifact"), record, registry)


BREAKS = {
    "empty content": _record(size_bytes=0),
    "a file over 50 MB": _record(media_type="application/pdf", size_bytes=50_000_001),
    **{f"{t} over 2 MB": _record(media_type=t, size_bytes=2_000_001) for t in TEXT_TYPES},
    "HTML is not a media type": _record(media_type="text/html"),
    "SVG is not a media type": _record(media_type="image/svg+xml"),
    "upper-case hash": _record(content_sha256=SHA.upper()),
    "short hash": _record(content_sha256=SHA[:63]),
    "a blob path field": _record(blob_key="orgs/org_example/worlds/w_example/artifacts/art_report/v000001"),
    "an id with a slash (AR-03)": _record(org_id="org_a/b"),
    "a unit output without an idempotency key": _record(idempotency_key=None),
    "an upload with an idempotency key": _record(origin=UPLOAD),
    "an eleventh output": _record(idempotency_key="r_example_1:U2:1:10"),
    "a unit origin without its unit": _record(origin={"kind": "unit", "unit": None, "agent": "A_s1"}),
    "an upload made by an agent": _record(
        origin={"kind": "upload", "unit": None, "agent": "A_s1"}, idempotency_key=None
    ),
    "two parents": _record(parents=[{"artifact_id": "art_report", "version": n} for n in (1, 2)]),
    "unknown screening": _record(screening="skipped"),
    "redacted is not a boolean": _record(redacted="no"),
    "a source that is not a run/seq pointer": _record(
        sources=[{"id": "src_market", "archive_ref": "https://example.com/a"}]
    ),
}


@pytest.mark.parametrize("case", sorted(BREAKS))
def test_FR_MEM_12_artifact_records_that_fail(repo_root, registry, case):
    assert errors_for(load_schema(repo_root, "artifact"), BREAKS[case], registry), case


def test_FR_MEM_12_manifest_revision(repo_root, registry):
    schema = load_schema(repo_root, "artifact")
    revision = schema["$defs"]["manifest_revision"]
    manifest = load_json(repo_root / "contracts/fixtures/manifest/valid/first_version_in_app.json")
    sample = {"n": 2, "stage": "reviewed", "cause": "01JB5VQ0000000000000000033", "manifest": manifest}
    wrapped = {"$ref": "https://contracts.tilo.example/artifact.schema.json#/$defs/manifest_revision"}
    assert set(revision["properties"]["stage"]["enum"]) == {"created", "reviewed", "sent", "exported"}
    assert not errors_for(wrapped, sample, registry)
    for change in ({"stage": "edited"}, {"n": 0}, {"cause": "evt_1"}, {"manifest": {"v": "1.0"}}):
        assert errors_for(wrapped, sample | change, registry), change


def test_FR_MEM_12_artifact_created_data_is_1_1_0_and_additive(repo_root, registry):
    schema = load_json(repo_root / "contracts/events/data/artifact.created.schema.json")
    assert (schema["x-version"], schema["required"]) == ("1.1.0", ["artifact"])
    assert not errors_for(schema, {"artifact": STORED["artifact"]}, registry), "1.0.0 events stay valid"
    assert not errors_for(schema, STORED, registry)
    for change in (
        {"media_type": "text/html"},
        {"size_bytes": 0},
        {"size_bytes": 2_000_001},
        {"content_sha256": SHA.upper()},
    ):
        assert errors_for(schema, STORED | change, registry), change
    for missing in ("content_sha256", "media_type", "size_bytes"):
        partial = {k: v for k, v in STORED.items() if k != missing}
        assert errors_for(schema, partial, registry), f"all three or none, {missing} missing"


def test_FR_MEM_12_fixtures_cover_the_artifact_contract(repo_root):
    fixtures = repo_root / "contracts/fixtures"
    for folder in ("artifact/valid", "artifact/invalid", "artifact.manifest_revision/valid"):
        assert list((fixtures / folder).glob("*.json")), folder
    assert list((fixtures / "artifact.manifest_revision/invalid").glob("*.json"))
    stored = load_json(fixtures / "events/valid/artifact.created--stored.json")["data"]
    assert {"content_sha256", "media_type", "size_bytes"} <= stored.keys()


def _stream(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _layout_ids(repo_root, events_module):
    return events_module.layout_ids(load_json(repo_root / "contracts/fixtures/layout/valid/village_basic.json"))


def test_FR_MEM_12_EV_15_versions_restore_review_and_delivery_stream_is_valid(repo_root):
    validate, events = _scripts(repo_root)
    stream = _stream(repo_root / "contracts/fixtures/streams/artifact-versions.jsonl")
    registry = events.load_registry(repo_root / "contracts")
    assert [p for e in stream for p in events.event_problems(e, registry, validate)] == []
    assert events.stream_problems(stream, _layout_ids(repo_root, events)) == []
    assert {e["type"] for e in stream} >= {f"artifact.{v}" for v in ("created", "versioned", "rolled_back")}
    assert {e["type"] for e in stream} >= {"artifact.reviewed", "artifact.delivered"}


INVALID_STREAMS = (
    "ev15_created_names_version_2",
    "ev15_reviewed_version_never_recorded",
    "ev15_delivered_before_created",
    "ev15_delivered_other_artifact",
    "ev15_versioned_previous_never_recorded",
    "ev15_rolled_back_restored_never_recorded",
)


@pytest.mark.parametrize("name", INVALID_STREAMS)
def test_FR_CON_15_EV_15_delivery_names_only_what_the_world_created(repo_root, name):
    validate, events = _scripts(repo_root)
    stream = _stream(repo_root / f"contracts/fixtures/streams/invalid/{name}.jsonl")
    registry = events.load_registry(repo_root / "contracts")
    assert [p for e in stream for p in events.event_problems(e, registry, validate)] == [], "passes the schemas"
    problems = events.stream_problems(stream, _layout_ids(repo_root, events))
    assert problems and all(p.startswith("EV-15") for p in problems), problems


def test_FR_MEM_12_EV_15_and_AR_rules_are_written_down(repo_root):
    assert "| EV-15 |" in (repo_root / "contracts/event.rules.md").read_text(encoding="utf-8")
    rules = (repo_root / "contracts/artifact.rules.md").read_text(encoding="utf-8")
    assert all(f"| AR-0{n} |" in rules for n in range(1, 9))


def test_FR_MEM_12_generated_types(repo_root):
    python = (repo_root / "packages/contracts-py/src/tilo_contracts/__init__.py").read_text(encoding="utf-8")
    typescript = (repo_root / "packages/contracts-ts/src/index.ts").read_text(encoding="utf-8")
    for name in ("ArtifactVersion", "ArtifactVersionManifestRevision", "ArtifactVersionOrigin"):
        assert re.search(rf"^class {name}\(", python, re.M) and f"export interface {name} " in typescript
    assert re.search(r"^type MediaType = Literal\[", python, re.M) and "export type MediaType =" in typescript
    created = typescript.split("export interface ArtifactCreatedData {", 1)[1].split("}", 1)[0]
    assert all(f"{field}?:" in created for field in ("content_sha256", "media_type", "size_bytes"))
