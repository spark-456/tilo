"""FR-MEM-06 hardening (security review of the store): an interrupted write leaves no orphan blob and never blocks the
next version, a restore or a restart; retention and erasure list every stored blob's record; the default
`.tilo/artifacts/` is gitignored (ADR-0018 section 2); the store checks `screened_at`, its id source, the world cap
before a restore hashes, and announces one `alert.raised` per corrupt version. API: API_FR_MEM_06.md."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from _artifact_testlib import (
    ARTICLE,
    MAX_FILE,
    OWNER,
    REPO_ROOT,
    T0,
    Clock,
    Redactor,
    Sized,
    SizeOnlyBlobs,
    blob_key,
    make_manifest,
    make_rig,
    record_path,
)
from _memory_lib import build_registry
from tilo_memory.artifacts import (
    GRACE,
    ArtifactBusy,
    ArtifactCorrupt,
    ArtifactError,
    ArtifactNotFound,
    ArtifactRefused,
    LocalDirBlobBackend,
    MemoryBlobBackend,
    MemoryMetaBackend,
)
from tilo_memory.erasure import REQUIRED_STORES, erase_user, request_erasure, verify_erasure
from tilo_memory.retention import purge_expired


class FlakyBlobs(MemoryBlobBackend):
    def __init__(self) -> None:
        super().__init__()
        self.fail_create = False

    def create(self, key: str, data: bytes) -> None:
        if self.fail_create:
            raise OSError("disk full")
        super().create(key, data)


class FlakyMeta(MemoryMetaBackend):
    def __init__(self) -> None:
        super().__init__()
        self.fail_delete = False

    def delete(self, path: str) -> None:
        if self.fail_delete:
            raise OSError("meta down")
        super().delete(path)


def _interrupted(tmp_path):
    """A store whose next put dies after the record is written: the blob create fails and so does the cleanup."""
    blobs, meta = FlakyBlobs(), FlakyMeta()
    return make_rig("custom", tmp_path, blobs=blobs, meta=meta), blobs, meta


def _crash_put(rig, blobs, meta, content=b"never lands", **kw):
    blobs.fail_create = meta.fail_delete = True
    try:
        with pytest.raises(OSError):
            rig.put(content, **kw)
    finally:
        blobs.fail_create = meta.fail_delete = False


# --- blocking 1: no orphan blob, no stuck version -------------------------------------------------


def test_FR_MEM_06_AR_08_an_interrupted_write_is_listed_so_retention_and_erasure_purge_it(tmp_path):
    rig, blobs, meta = _interrupted(tmp_path)
    v1 = rig.put(ARTICLE)
    _crash_put(rig, blobs, meta, parent=v1.ref)
    (leftover,) = [r for r in rig.store.retention().records() if r.record_id != record_path(rig.scope, v1.ref)]
    assert leftover.user_id == OWNER and blobs.keys() == [blob_key(rig.scope, v1.ref)], "no blob without a record"

    registry = build_registry(sorted(REQUIRED_STORES)) | {"gcs_artifacts": rig.store.retention()}
    assert purge_expired(registry, now=T0 + timedelta(days=91))["gcs_artifacts"] == 2
    assert rig.meta.inner.paths() == [] and blobs.keys() == []


def test_FR_MEM_06_AR_08_an_interrupted_write_is_erased_with_its_owner(tmp_path):
    rig, blobs, meta = _interrupted(tmp_path)
    v1 = rig.put(ARTICLE)
    _crash_put(rig, blobs, meta, parent=v1.ref)
    registry = build_registry(sorted(REQUIRED_STORES)) | {"gcs_artifacts": rig.store.retention()}
    now = datetime(2026, 10, 6, tzinfo=UTC)
    assert verify_erasure(registry, OWNER).remaining["gcs_artifacts"] == 2
    report = erase_user(registry, request_erasure(OWNER, requested_at=now), now=now)
    assert report.complete is True and report.removed["gcs_artifacts"] == 2
    assert rig.meta.inner.paths() == [] and blobs.keys() == []


def test_FR_MEM_06_AR_02_an_interrupted_write_never_blocks_the_next_version_or_a_restore(tmp_path):
    rig, blobs, meta = _interrupted(tmp_path)
    v1 = rig.put(b"one")
    _crash_put(rig, blobs, meta, parent=v1.ref)  # version 2 is a record with no blob: it reads as corrupt
    with pytest.raises(ArtifactCorrupt):
        rig.store.read(rig.scope, {"artifact_id": v1.artifact_id, "version": 2})

    v3 = rig.put(b"three", parent=v1.ref)
    restored = rig.restore(v1.ref)
    assert (v3.version, restored.version) == (3, 4)
    assert rig.store.read(rig.scope, v3.ref) == b"three" and rig.store.read(rig.scope, restored.ref) == b"one"


def test_FR_MEM_06_AR_02_an_orphan_blob_without_a_record_is_never_deleted_or_rewritten():
    rig = make_rig("memory", None)
    v1 = rig.put(b"one")
    v2 = rig.put(b"two", parent=v1.ref)
    rig.meta.inner.delete(record_path(rig.scope, v2.ref))  # a record lost, its blob left behind
    with pytest.raises(ArtifactCorrupt):  # the blob is not these bytes: it is reported, not replaced
        rig.put(b"two, again", parent=v1.ref)
    assert rig.blobs.inner.read(blob_key(rig.scope, v2.ref)) == b"two", "a committed blob is never rewritten"
    assert rig.put(b"three", parent=v1.ref).version == 3, "and the version it holds does not block the next one"
    (held,) = [r for r in rig.store.retention().records() if r.record_id == record_path(rig.scope, v2.ref)]
    rig.store.retention().delete(held.record_id)  # the record we hold for it is listed, so it is purged and erased
    assert blob_key(rig.scope, v2.ref) not in rig.blobs.inner.keys()


def test_FR_MEM_06_AR_02_an_orphan_blob_with_the_same_bytes_is_accepted_as_a_create_only_fill_in():
    rig = make_rig("memory", None)
    v1 = rig.put(b"one")
    v2 = rig.put(b"two", parent=v1.ref)
    rig.meta.inner.delete(record_path(rig.scope, v2.ref))
    again = rig.put(b"two", parent=v1.ref)
    assert again.version == 2 and rig.store.read(rig.scope, again.ref) == b"two"


def test_FR_MEM_06_AR_05_a_restarted_unit_redoes_an_interrupted_put_once_the_grace_window_has_passed(tmp_path):
    rig, blobs, meta = _interrupted(tmp_path)
    _crash_put(rig, blobs, meta, b"first try", attempt=1)
    with pytest.raises(ArtifactBusy):  # inside the window it may be another writer's: retry later, change nothing
        rig.put(b"second try", attempt=1)
    assert len(rig.meta.inner.paths()) == 1
    rig.clock.advance(GRACE + timedelta(seconds=1))
    again = rig.put(b"second try", attempt=1)
    assert again.version == 1
    assert rig.store.read(rig.scope, again.ref) == b"second try"
    assert rig.put(b"third try", attempt=1) == again, "and now the key is settled: first stored bytes win"


def test_FR_MEM_06_AR_02_a_failed_blob_write_with_a_working_store_leaves_nothing(tmp_path):
    rig, blobs, _ = _interrupted(tmp_path)
    blobs.fail_create = True
    with pytest.raises(OSError):
        rig.put(ARTICLE)
    assert rig.meta.inner.paths() == [] and blobs.keys() == []


# --- blocking 2: the default local directory is ignored -----------------------------------------------


@pytest.mark.parametrize("path", [".tilo/artifacts/orgs/x/v000001", "packages/memory/.tilo/artifacts/x"])
def test_FR_MEM_06_the_default_artifact_dir_is_gitignored(path):
    done = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, capture_output=True, check=False)
    assert done.returncode == 0, f"{path} must be ignored (ADR-0018 section 2)"


# --- follow-ups ------------------------------------------------------------------------------------------


def test_FR_MEM_06_the_id_source_must_return_a_whole_artifact_id(tmp_path):
    for bad in ("art_ok\n", "art_a/../b", "x", ""):
        rig = make_rig("memory", tmp_path, new_id=lambda bad=bad: bad)
        with pytest.raises(ArtifactError):
            rig.put(ARTICLE)
        assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


def test_FR_MEM_06_AR_07_a_screened_at_after_created_at_is_refused(tmp_path):
    rig = make_rig("memory", tmp_path, clock=Clock(tick=timedelta(seconds=-1)))  # the clock runs backwards
    with pytest.raises(ArtifactRefused):
        rig.put(ARTICLE)
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


def test_FR_MEM_06_AR_04_a_restore_over_the_world_cap_is_refused_before_hashing(tmp_path):
    big = make_rig("custom", tmp_path, blobs=SizeOnlyBlobs())
    first = big.upload(Sized(MAX_FILE), "application/pdf")
    for _ in range(3):
        big.upload(Sized(MAX_FILE), "application/pdf")
    hashed = big.hasher.calls
    with pytest.raises(ArtifactRefused):
        big.restore(first.ref)
    assert big.hasher.calls == hashed


def test_FR_MEM_06_AR_06_add_manifest_rereads_the_record_inside_the_lock(tmp_path):
    class Deleting(Redactor):
        armed = False
        store = None

        def __call__(self, text):
            if self.armed and "example.com" in text:
                self.armed = False
                (record,) = self.store.retention().records()
                self.store.retention().delete(record.record_id)  # retention purges it mid-call
            return super().__call__(text)

    redactor = Deleting()
    rig = make_rig("memory", tmp_path, redactor=redactor)
    redactor.store = rig.store
    rig.archive.add(rig.scope, "r_run1/7")
    v1 = rig.put(ARTICLE, sources=({"id": "src_market", "archive_ref": "r_run1/7"},))
    redactor.armed = True
    with pytest.raises(ArtifactNotFound):
        rig.store.add_manifest(rig.scope, v1.ref, make_manifest(v1), stage="created", cause=None)
    assert rig.meta.inner.paths() == []


@pytest.mark.parametrize(
    "key", ["orgs/a.b/v1", "orgs/a b/v1", "orgs/é/v1", "orgs/a-b/v1", "orgs/./v1", "orgs/a/v1/", "orgs\\a"]
)
def test_FR_MEM_06_local_dir_backend_allows_only_id_characters_in_each_segment(tmp_path, key):
    with pytest.raises(ValueError):
        LocalDirBlobBackend(tmp_path / "root").create(key, b"x")
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_FR_MEM_06_AR_01_one_alert_per_corrupt_version_not_one_per_failed_read(tmp_path):
    rig = make_rig("memory", tmp_path)
    stored = rig.put(ARTICLE)
    rig.tamper(stored, b"tampered")
    for _ in range(3):
        with pytest.raises(ArtifactCorrupt):
            rig.store.read(rig.scope, stored.ref)
    assert len(rig.alerts) == 1
    rig.tamper(stored, ARTICLE)  # repaired: a clean read re-arms the alert
    assert rig.store.read(rig.scope, stored.ref) == ARTICLE
    rig.tamper(stored, b"tampered again")
    with pytest.raises(ArtifactCorrupt):
        rig.store.read(rig.scope, stored.ref)
    assert len(rig.alerts) == 2
