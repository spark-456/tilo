"""FR-MEM-06 (PRD 13.2, 13.4): "Restore v2: v3 is identical to v2". AR-01 (read re-hashes), AR-02 (versions, parents,
never rewritten, restore is an exact copy), the record is validated against the JSON Schema, and the memory and
local-dir backends pass the same suite. Sources: docs/adr/0018-artifact-output-and-store.md sections 2 and 3,
contracts/artifact.rules.md. API: API_FR_MEM_06.md. `tilo_memory.artifacts` does not exist yet, so these fail at
import."""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from _artifact_testlib import (
    ARTICLE,
    CONTRACTS,
    JSON_DOC,
    ORG,
    OWNER,
    RUN,
    SECRET,
    T0,
    WORLD,
    Clock,
    FakeSafety,
    Redactor,
    Sized,
    SizeOnlyBlobs,
    blob_key,
    iso,
    make_rig,
    record_path,
    schema_errors,
    sha,
)
from tilo_memory.artifacts import (
    ArtifactCorrupt,
    ArtifactNotFound,
    ArtifactRefused,
    ArtifactStore,
    LocalDirBlobBackend,
    MemoryBlobBackend,
    MemoryMetaBackend,
    NewVersion,
    Origin,
    validate_record,
)

ULID_ID = re.compile(r"art_[0-7][0-9A-HJKMNP-TV-Z]{25}")


@pytest.fixture(params=["memory", "local"])
def rig(request, tmp_path):
    return make_rig(request.param, tmp_path)


# --- AR-01: every read re-hashes ------------------------------------------------------------------


def test_FR_MEM_06_AR_01_read_returns_the_stored_bytes_and_the_record_holds_their_sha256(rig):
    stored = rig.put(ARTICLE)
    before = rig.hasher.calls
    assert rig.store.read(rig.scope, stored.ref) == ARTICLE
    assert rig.hasher.calls > before, "a read must recompute the hash (AR-01)"
    assert stored.record["content_sha256"] == sha(ARTICLE)
    assert stored.record["size_bytes"] == len(ARTICLE)
    assert rig.alerts == []


@pytest.mark.parametrize(
    "tampered",
    [
        pytest.param(lambda b: b[:-1] + bytes([b[-1] ^ 1]), id="one-bit-flip-same-length"),
        pytest.param(lambda b: b[:-3], id="truncated"),
        pytest.param(lambda b: b + b"extra", id="appended"),
        pytest.param(lambda b: b"x", id="replaced"),
    ],
)
def test_FR_MEM_06_AR_01_tampered_blob_raises_corrupt_and_is_never_served(rig, tampered):
    stored = rig.put(ARTICLE)
    bad = tampered(ARTICLE)
    rig.tamper(stored, bad)
    for _ in range(2):  # and it stays refused: nothing is cached from the first failure
        with pytest.raises(ArtifactCorrupt) as info:
            rig.store.read(rig.scope, stored.ref)
        assert "Market brief" not in str(info.value), "an error never carries content"


def test_FR_MEM_06_AR_01_a_failed_read_emits_one_alert_raised_through_the_sink(rig):
    stored = rig.put(ARTICLE)
    rig.store.read(rig.scope, stored.ref)
    assert rig.alerts == [], "a clean read raises no alert"

    rig.tamper(stored, ARTICLE + b"!")
    with pytest.raises(ArtifactCorrupt):
        rig.store.read(rig.scope, stored.ref)

    assert len(rig.alerts) == 1
    alert = rig.alerts[0]
    assert alert["type"] == "alert.raised"
    assert alert["world_id"] == WORLD and alert["run_id"] == RUN
    assert alert["artifact"] == stored.ref
    assert schema_errors(alert["data"], "events/data/alert.raised.schema.json") == []
    assert alert["data"]["card_id"] is None
    assert "Market brief" not in json.dumps(alert), "an alert never carries content"


def test_FR_MEM_06_AR_01_a_missing_blob_for_an_existing_record_is_corrupt_not_served(rig):
    # ASSUMPTION (AR-01 "never served"): record present, bytes gone = corrupt, with an alert, not "absent".
    stored = rig.put(ARTICLE)
    rig.blobs.inner.delete(blob_key(rig.scope, stored.ref))
    with pytest.raises(ArtifactCorrupt):
        rig.store.read(rig.scope, stored.ref)
    assert len(rig.alerts) == 1


def test_FR_MEM_06_AR_01_head_is_metadata_only_and_a_corrupt_version_does_not_block_its_siblings(rig):
    v1 = rig.put(ARTICLE)
    v2 = rig.put(b"second draft", parent=v1.ref)
    rig.tamper(v1, b"tampered")
    rig.blobs.calls.clear()

    assert rig.store.head(rig.scope, v1.ref) == v1, "head reports metadata without reading or judging the blob"
    assert rig.blobs.called("read") == []
    assert rig.store.read(rig.scope, v2.ref) == b"second draft"
    with pytest.raises(ArtifactCorrupt):
        rig.store.read(rig.scope, v1.ref)


# --- AR-02: versions, parents, never rewritten ----------------------------------------------------


def test_FR_MEM_06_AR_02_versions_run_1_2_3_with_no_gaps_and_parents_chain(rig):
    v1 = rig.put(b"one")
    v2 = rig.put(b"two", parent=v1.ref)
    v3 = rig.put(b"three", parent=v2.ref)
    assert [v.version for v in (v1, v2, v3)] == [1, 2, 3]
    assert v1.artifact_id == v2.artifact_id == v3.artifact_id
    assert ULID_ID.fullmatch(v1.artifact_id), "the store mints art_<ULID> ids"
    assert v1.record["parents"] == []
    assert v2.record["parents"] == [v1.ref]
    assert v3.record["parents"] == [v2.ref]
    listed = rig.store.versions(rig.scope, v1.artifact_id)
    assert [v.version for v in listed] == [1, 2, 3]
    assert [rig.store.read(rig.scope, v.ref) for v in listed] == [b"one", b"two", b"three"]


def test_FR_MEM_06_AR_02_a_parent_may_be_any_earlier_version_of_the_same_id(rig):
    v1 = rig.put(b"one")
    v2 = rig.put(b"two", parent=v1.ref)
    v3 = rig.put(b"three", parent=v2.ref)
    v4 = rig.put(b"four, continuing one", parent=v1.ref)
    assert v4.version == 4 and v4.artifact_id == v1.artifact_id
    assert v4.record["parents"] == [v1.ref], "exactly one earlier version of the same id (schema: at most one)"
    assert [v.version for v in rig.store.versions(rig.scope, v1.artifact_id)] == [1, 2, 3, 4]
    assert v3.version == 3


def test_FR_MEM_06_AR_02_a_new_artifact_gets_a_minted_id_and_the_caller_cannot_choose_one(rig):
    first, second = rig.put(b"a"), rig.put(b"b")
    assert first.artifact_id != second.artifact_id
    assert first.version == second.version == 1
    assert first.record["parents"] == [] and second.record["parents"] == []
    with pytest.raises(TypeError):
        NewVersion(  # type: ignore[call-arg]
            media_type="text/markdown",
            content=b"x",
            run_id=RUN,
            origin=Origin(kind="upload"),
            artifact_id="art_chosen",
        )


def test_FR_MEM_06_AR_02_a_parent_that_does_not_exist_is_refused_and_stores_nothing(rig):
    v1 = rig.put(b"one")
    keys_before = rig.blobs.inner.keys()
    for ghost in ({"artifact_id": "art_never_existed", "version": 1}, {"artifact_id": v1.artifact_id, "version": 5}):
        with pytest.raises(ArtifactNotFound):
            rig.put(b"orphan", parent=ghost)
    assert rig.blobs.inner.keys() == keys_before
    assert [v.version for v in rig.store.versions(rig.scope, v1.artifact_id)] == [1]


@pytest.mark.parametrize("backend", ["meta", "memory-blobs", "local-blobs", "size-only-blobs"])
def test_FR_MEM_06_AR_02_a_backend_never_rewrites_an_existing_key(backend, tmp_path):
    if backend == "meta":
        store = MemoryMetaBackend()
        store.create("orgs/o/worlds/w/artifacts/art_x/versions/000001", {"n": 1})
        with pytest.raises(FileExistsError):
            store.create("orgs/o/worlds/w/artifacts/art_x/versions/000001", {"n": 2})
        assert store.get("orgs/o/worlds/w/artifacts/art_x/versions/000001") == {"n": 1}
        return
    blobs = {
        "memory-blobs": MemoryBlobBackend,
        "local-blobs": lambda: LocalDirBlobBackend(tmp_path / "blobs"),
        "size-only-blobs": SizeOnlyBlobs,
    }[backend]()
    key = "orgs/o/worlds/w/artifacts/art_x/v000001"
    blobs.create(key, b"first")
    with pytest.raises(FileExistsError):
        blobs.create(key, b"second")
    assert blobs.read(key) == b"first"
    assert blobs.keys("orgs/o/") == [key]
    blobs.delete(key)
    blobs.delete(key)  # idempotent
    assert blobs.keys() == []
    with pytest.raises(FileNotFoundError):
        blobs.read(key)


def test_FR_MEM_06_AR_02_a_put_creates_exactly_one_blob_and_one_record_at_the_adr_paths(rig):
    stored = rig.put(ARTICLE)
    assert rig.blobs.inner.keys() == [blob_key(rig.scope, stored.ref)]
    assert blob_key(rig.scope, stored.ref) == f"orgs/{ORG}/worlds/{WORLD}/artifacts/{stored.artifact_id}/v000001"
    created = rig.meta.called("create")
    assert [c[1][0] for c in created] == [record_path(rig.scope, stored.ref)]
    assert validate_record(created[0][1][1]) is None, "the stored document is a valid ArtifactVersion"
    assert created[0][1][1] == stored.record
    v2 = rig.put(b"two", parent=stored.ref)
    assert rig.blobs.inner.keys() == [blob_key(rig.scope, stored.ref), blob_key(rig.scope, v2.ref)]
    assert rig.store.read(rig.scope, stored.ref) == ARTICLE, "v1 is untouched by v2"


def test_FR_MEM_06_AR_02_the_record_matches_the_json_schema_and_comes_from_scope_and_clock(rig):
    rig.archive.add(rig.scope, f"{RUN}/7")
    stored = rig.put(ARTICLE, sources=({"id": "src_market", "archive_ref": f"{RUN}/7"},))
    record = stored.record
    assert schema_errors(record, "artifact.schema.json") == []
    assert (record["org_id"], record["world_id"], record["owner"], record["run_id"]) == (ORG, WORLD, OWNER, RUN)
    assert record["v"] == "1.0" and record["media_type"] == "text/markdown"
    assert record["created_at"] == iso(T0)
    assert record["origin"] == {"kind": "unit", "unit": "U1", "agent": "A_s1"}
    assert record["idempotency_key"].startswith(f"{RUN}:U1:")
    assert "blob" not in json.dumps(record).lower().replace("sources", ""), "no blob path field in the record"


# --- FR-MEM-06 restore ----------------------------------------------------------------------------


def test_FR_MEM_06_restore_v2_then_v3_is_byte_identical_to_v2_with_parents_v2(rig):
    v1 = rig.put(b"first draft")
    v2 = rig.put(b"second draft, the one to keep", parent=v1.ref)
    rig.clock.advance(timedelta(minutes=10))

    v3 = rig.restore(v2.ref)

    assert (v3.artifact_id, v3.version) == (v2.artifact_id, 3), "a restore is a new version, not a rewrite"
    assert rig.store.read(rig.scope, v3.ref) == rig.store.read(rig.scope, v2.ref) == b"second draft, the one to keep"
    assert v3.record["content_sha256"] == v2.record["content_sha256"]
    assert v3.record["parents"] == [v2.ref]
    assert v3.record["origin"] == {"kind": "restore", "unit": None, "agent": None}
    assert v3.record["idempotency_key"] is None
    assert v3.record["created_at"] == iso(T0 + timedelta(minutes=10))
    assert schema_errors(v3.record, "artifact.schema.json") == []
    # the history is untouched
    assert rig.store.read(rig.scope, v1.ref) == b"first draft"
    assert rig.store.head(rig.scope, v2.ref) == v2


def test_FR_MEM_06_restore_of_an_older_version_appends_the_next_version(rig):
    v1 = rig.put(b"one")
    v2 = rig.put(b"two", parent=v1.ref)
    v3 = rig.put(b"three", parent=v2.ref)
    v4 = rig.restore(v1.ref)
    assert v4.version == 4 and v4.record["parents"] == [v1.ref]
    assert rig.store.read(rig.scope, v4.ref) == b"one"
    assert rig.store.read(rig.scope, v3.ref) == b"three"
    v5 = rig.restore(v1.ref)  # a restore has no idempotency key: restoring again is another version
    assert v5.version == 5 and v5.record["parents"] == [v1.ref]
    assert [v.version for v in rig.store.versions(rig.scope, v1.artifact_id)] == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param({"safety": FakeSafety(), "content": ARTICLE, "type": "text/markdown"}, id="clean-markdown"),
        pytest.param(
            {"safety": FakeSafety(flagged=True), "content": JSON_DOC, "type": "application/json"}, id="flagged"
        ),
        pytest.param({"safety": None, "content": b"a,b\n1,2\n", "type": "text/csv"}, id="unscreened"),
        pytest.param(
            {"safety": FakeSafety(), "content": ARTICLE + SECRET.encode(), "type": "text/markdown"}, id="redacted"
        ),
    ],
)
def test_FR_MEM_06_AR_02_restore_is_an_exact_copy_of_bytes_type_sources_screening_and_redaction(case, tmp_path):
    rig = make_rig("memory", tmp_path, safety=case["safety"], clock=Clock(tick=timedelta(seconds=1)))
    src = {"id": "src_market", "archive_ref": f"{RUN}/7"}
    rig.archive.add(rig.scope, src["archive_ref"])
    original = rig.put(case["content"], media_type=case["type"], sources=(src,))
    screener_calls = len(rig.safety.calls) if rig.safety else 0
    redactor_calls = len(rig.redactor.calls)
    rig.archive.remove(rig.scope, src["archive_ref"])  # a restore copies sources; it does not re-check or add any

    restored = rig.restore(original.ref)

    for field in (
        "media_type",
        "size_bytes",
        "content_sha256",
        "sources",
        "screening",
        "screened_at",
        "redacted",
        "run_id",
        "owner",
    ):
        assert restored.record[field] == original.record[field], field
    assert rig.store.read(rig.scope, restored.ref) == rig.store.read(rig.scope, original.ref)
    assert (len(rig.safety.calls) if rig.safety else 0) == screener_calls, "a restore is not screened again"
    assert len(rig.redactor.calls) == redactor_calls, "a restore is not redacted again"
    assert restored.record["created_at"] != original.record["created_at"], "the restore has its own time"
    assert schema_errors(restored.record, "artifact.schema.json") == []


def test_FR_MEM_06_AR_02_a_restore_cannot_add_sources_or_claim_a_different_origin(rig):
    src = {"id": "src_market", "archive_ref": f"{RUN}/7"}
    rig.archive.add(rig.scope, src["archive_ref"])
    original = rig.put(ARTICLE, sources=(src,))
    rig.archive.add(rig.scope, f"{RUN}/9")
    with pytest.raises(TypeError):
        rig.store.restore(  # type: ignore[call-arg]
            rig.scope, original.ref, by=Origin(kind="restore"), sources=[{"id": "extra", "archive_ref": f"{RUN}/9"}]
        )
    with pytest.raises(ArtifactRefused):
        rig.store.restore(rig.scope, original.ref, by=Origin(kind="unit", unit="U1", agent="A_s1"))
    with pytest.raises(ArtifactRefused):
        rig.store.put(
            rig.scope,
            NewVersion(
                media_type="text/markdown",
                content=b"x",
                run_id=RUN,
                origin=Origin(kind="restore"),
                idempotency_key=None,
            ),
        )
    assert [v.version for v in rig.store.versions(rig.scope, original.artifact_id)] == [1]
    restored = rig.restore(original.ref)
    assert restored.record["sources"] == [src]


def test_FR_MEM_06_AR_01_restore_of_a_tampered_version_raises_corrupt_and_creates_no_version(rig):
    v1 = rig.put(ARTICLE)
    rig.tamper(v1, b"tampered")
    keys = rig.blobs.inner.keys()
    with pytest.raises(ArtifactCorrupt):
        rig.restore(v1.ref)
    assert rig.blobs.inner.keys() == keys
    assert [v.version for v in rig.store.versions(rig.scope, v1.artifact_id)] == [1]
    assert len(rig.alerts) == 1


# --- records are validated against the JSON Schema, not only the pydantic model -------------------


def _fixture_files(folder: str) -> list[Path]:
    return sorted((CONTRACTS / "fixtures" / folder).glob("*.json"))


def test_FR_MEM_06_validate_record_is_the_json_schema_valid_and_invalid_fixtures():
    valid, invalid = _fixture_files("artifact/valid"), _fixture_files("artifact/invalid")
    assert len(valid) >= 6 and len(invalid) >= 30
    for path in valid:
        validate_record(json.loads(path.read_text(encoding="utf-8")))
    for path in invalid:
        with pytest.raises(Exception):  # noqa: B017 - jsonschema.ValidationError or ArtifactRefused
            validate_record(json.loads(path.read_text(encoding="utf-8")))
        # (every invalid fixture is also one the generated pydantic model may accept: the conditional rules are the
        # schema's, which is why the store runs the schema itself)


def test_FR_MEM_06_the_store_runs_record_validation_on_every_put_and_restore(tmp_path):
    seen: list[dict] = []

    def spy(record: dict) -> None:
        seen.append(record)
        validate_record(record)

    rig = make_rig("memory", tmp_path, record_validator=spy)
    v1 = rig.put(ARTICLE)
    rig.restore(v1.ref)
    assert [r["artifact"]["version"] for r in seen] == [1, 2]
    assert all(schema_errors(r, "artifact.schema.json") == [] for r in seen)


def test_FR_MEM_06_a_record_the_validator_rejects_is_refused_and_nothing_is_stored(tmp_path):
    def reject(record: dict) -> None:
        raise ValueError("schema says no")

    rig = make_rig("memory", tmp_path, record_validator=reject)
    with pytest.raises((ArtifactRefused, ValueError)):
        rig.put(ARTICLE)
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


def test_FR_MEM_06_pydantic_valid_but_schema_invalid_records_are_refused(tmp_path):
    """Both are accepted by the generated pydantic ArtifactVersion (it drops the schema's conditional rules)."""
    rig = make_rig("custom", tmp_path, blobs=SizeOnlyBlobs())
    with pytest.raises(ArtifactRefused):  # 40,000,000 bytes of text/markdown: the schema caps text at 2,000,000
        rig.put(Sized(40_000_000), media_type="text/markdown")
    with pytest.raises(ArtifactRefused):  # origin unit with a null unit
        rig.store.put(
            rig.scope,
            NewVersion(
                media_type="text/markdown",
                content=ARTICLE,
                run_id=RUN,
                origin=Origin(kind="unit", unit=None, agent="A_s1"),
                idempotency_key=f"{RUN}:U1:1:0",
            ),
        )
    with pytest.raises(ArtifactRefused):  # origin unit without an agent
        rig.store.put(
            rig.scope,
            NewVersion(
                media_type="text/markdown",
                content=ARTICLE,
                run_id=RUN,
                origin=Origin(kind="unit", unit="U1", agent=None),
                idempotency_key=f"{RUN}:U1:1:0",
            ),
        )
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


# --- collaborators are required, never defaulted away ---------------------------------------------


@pytest.mark.parametrize("missing", ["clock", "redactor", "archive_lookup", "alert_sink"])
def test_FR_MEM_06_AR_07_the_store_cannot_be_built_without_its_clock_redactor_archive_or_alert_sink(missing):
    kwargs = {
        "clock": Clock(),
        "redactor": Redactor(),
        "archive_lookup": lambda scope, ref: None,
        "alert_sink": lambda alert: None,
    }
    del kwargs[missing]
    with pytest.raises(TypeError):
        ArtifactStore(MemoryMetaBackend(), MemoryBlobBackend(), **kwargs)  # type: ignore[arg-type]


# --- both backends: the local-dir one derives paths from ids only ---------------------------------


def test_FR_MEM_06_local_dir_backend_writes_one_file_per_version_under_its_root_with_xb(tmp_path):
    rig = make_rig("local", tmp_path)
    stored = rig.put(ARTICLE)
    path = rig.root / blob_key(rig.scope, stored.ref)
    assert path.read_bytes() == ARTICLE
    files = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert files == [path], "nothing is written outside the version's own file"
    with pytest.raises(FileExistsError):
        rig.blobs.inner.create(blob_key(rig.scope, stored.ref), b"overwrite")
    assert path.read_bytes() == ARTICLE


@pytest.mark.parametrize(
    "key",
    ["../evil", "orgs/../../evil", "/abs/evil", "orgs//evil", "orgs\\evil", "C:/evil", "orgs/ok/../../../evil", ""],
)
def test_FR_MEM_06_local_dir_backend_refuses_keys_that_could_leave_its_root(tmp_path, key):
    backend = LocalDirBlobBackend(tmp_path / "root")
    with pytest.raises(ValueError):
        backend.create(key, b"x")
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_FR_MEM_06_local_dir_default_is_tilo_artifacts_and_TILO_ARTIFACT_DIR_overrides_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    default = LocalDirBlobBackend.from_env({})
    assert default.root.as_posix().rstrip("/").endswith(".tilo/artifacts")
    chosen = LocalDirBlobBackend.from_env({"TILO_ARTIFACT_DIR": str(tmp_path / "elsewhere")})
    assert Path(chosen.root) == tmp_path / "elsewhere"
    assert list(tmp_path.iterdir()) == [], "building a backend touches no disk"


def test_FR_MEM_06_both_backends_give_the_same_answers(tmp_path):
    memory, local = make_rig("memory", tmp_path / "m"), make_rig("local", tmp_path / "l")
    ids = []
    for rig in (memory, local):
        v1 = rig.put(b"one")
        v2 = rig.put(b"two", parent=v1.ref)
        v3 = rig.restore(v1.ref)
        ids.append(
            [
                (v.version, [p["version"] for p in v.record["parents"]], rig.store.read(rig.scope, v.ref))
                for v in (v1, v2, v3)
            ]
        )
    assert ids[0] == ids[1]
