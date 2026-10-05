"""FR-MEM-06 AR-02 / AR-08 (security re-check): a blob create that writes and then raises leaves no blob without a
listed record; and with two ArtifactStore instances over shared backends (T8: Cloud Run instances) one store never
purges, deletes or overwrites a record or blob that the other may still be completing. API: API_FR_MEM_06.md."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from _artifact_testlib import ARTICLE, OWNER, T0, Redactor, blob_key, make_rig
from _memory_lib import build_registry
from tilo_memory.artifacts import (
    GRACE,
    ArtifactBusy,
    ArtifactCorrupt,
    ArtifactStore,
    LocalDirBlobBackend,
    MemoryBlobBackend,
)
from tilo_memory.erasure import REQUIRED_STORES, erase_user, request_erasure, verify_erasure
from tilo_memory.retention import purge_expired


class WriteThenRaise:
    """A blob backend whose create commits (all or part of) the bytes and then raises, like an upload that lands and
    then times out, or a disk that fills mid-file. `fail_delete` makes delete raise too."""

    def __init__(self, inner, mode: str) -> None:
        self.inner, self.mode = inner, mode
        self.fail_create = self.fail_delete = False

    def create(self, key: str, data: bytes) -> None:
        if not self.fail_create:
            return self.inner.create(key, data)
        part = data if self.mode == "commit" else data[:3]
        if isinstance(self.inner, LocalDirBlobBackend):
            path = self.inner._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "xb") as handle:
                handle.write(part)
        else:
            self.inner.create(key, part)
        raise OSError(28, "no space left on device")

    def read(self, key: str) -> bytes:
        return self.inner.read(key)

    def delete(self, key: str) -> None:
        if self.fail_delete:
            raise OSError("blob store down")
        self.inner.delete(key)

    def keys(self, prefix: str = "") -> list[str]:
        return self.inner.keys(prefix)


@pytest.fixture(params=["memory-commit", "memory-partial", "local-commit", "local-partial"])
def flaky(request, tmp_path):
    backend, mode = request.param.split("-")
    inner = LocalDirBlobBackend(tmp_path / "blobs") if backend == "local" else MemoryBlobBackend()
    blobs = WriteThenRaise(inner, mode)
    return make_rig("custom", tmp_path, blobs=blobs), blobs


def _fail_put(rig, blobs, **kw):
    blobs.fail_create = True
    try:
        with pytest.raises(OSError):
            rig.put(ARTICLE, **kw)
    finally:
        blobs.fail_create = False


def test_FR_MEM_06_AR_08_a_create_that_wrote_and_raised_leaves_neither_blob_nor_record(flaky):
    rig, blobs = flaky
    _fail_put(rig, blobs)
    assert blobs.keys() == [] and rig.meta.inner.paths() == []


def test_FR_MEM_06_AR_08_if_the_blob_cannot_be_deleted_the_record_stays_listed_and_purge_removes_both(flaky):
    rig, blobs = flaky
    blobs.fail_delete = True
    _fail_put(rig, blobs)
    blobs.fail_delete = False
    (listed,) = rig.store.retention().records()
    assert len(blobs.keys()) == 1, "the bytes are still there ..."
    assert len(rig.meta.inner.paths()) == 1, "... so their record was kept"
    registry = {"gcs_artifacts": rig.store.retention()}
    assert purge_expired(registry, now=T0 + timedelta(days=91)) == {"gcs_artifacts": 1}
    assert blobs.keys() == [] and rig.meta.inner.paths() == [] and listed.user_id == OWNER


def test_FR_MEM_06_AR_08_if_the_blob_cannot_be_deleted_erasure_removes_the_bytes_too(flaky):
    rig, blobs = flaky
    blobs.fail_delete = True
    _fail_put(rig, blobs)
    blobs.fail_delete = False
    registry = build_registry(sorted(REQUIRED_STORES)) | {"gcs_artifacts": rig.store.retention()}
    now = datetime(2026, 10, 6, tzinfo=UTC)
    assert verify_erasure(registry, OWNER).remaining["gcs_artifacts"] == 1
    report = erase_user(registry, request_erasure(OWNER, requested_at=now), now=now)
    assert report.complete is True and report.removed["gcs_artifacts"] == 1
    assert blobs.keys() == [] and rig.meta.inner.paths() == []


def test_FR_MEM_06_AR_01_a_kept_record_is_judged_by_its_blob_and_a_bad_blob_is_never_repaired(flaky):
    rig, blobs = flaky
    blobs.fail_delete = True
    _fail_put(rig, blobs, attempt=1)
    blobs.fail_delete = False
    (listed,) = rig.store.retention().records()
    ref = {"artifact_id": listed.record_id.split("/")[5], "version": 1}
    if blobs.mode == "commit":  # the whole blob landed: the version is intact and the key is settled
        assert rig.store.read(rig.scope, ref) == ARTICLE
        assert rig.put(b"other bytes", attempt=1).ref == ref
        return
    with pytest.raises(ArtifactCorrupt):
        rig.store.read(rig.scope, ref)
    with pytest.raises(ArtifactBusy):  # inside the window the same key waits
        rig.put(ARTICLE, attempt=1)
    rig.clock.advance(GRACE + timedelta(seconds=1))
    with pytest.raises(ArtifactCorrupt):  # a bad blob is reported, not overwritten or purged
        rig.put(ARTICLE, attempt=1)
    assert len(blobs.keys()) == 1 and len(rig.meta.inner.paths()) == 1


# --- two stores over shared backends ---------------------------------------------------------------


class HeldBlobs(MemoryBlobBackend):
    """The next create pauses before it writes, as a slow upload would."""

    def __init__(self) -> None:
        super().__init__()
        self.hold = False
        self.entered, self.release = threading.Event(), threading.Event()

    def create(self, key: str, data: bytes) -> None:
        if self.hold:
            self.hold = False
            self.entered.set()
            assert self.release.wait(30)
        super().create(key, data)


def _two_stores(tmp_path):
    blobs = HeldBlobs()
    rig = make_rig("custom", tmp_path, blobs=blobs)
    other = ArtifactStore(
        rig.meta.inner,
        blobs,
        clock=rig.clock,
        redactor=Redactor(),
        archive_lookup=rig.archive,
        alert_sink=lambda alert: None,
    )
    return rig, blobs, other


def test_FR_MEM_06_AR_05_another_store_never_purges_a_record_whose_blob_is_still_being_written(tmp_path):
    rig, blobs, other = _two_stores(tmp_path)
    blobs.hold = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(rig.put, b"x", attempt=1)
        assert blobs.entered.wait(10)
        with pytest.raises(ArtifactBusy):  # same key, record present, blob not yet: retryable, not a repair
            other.put(rig.scope, rig.new(b"x", attempt=1))
        assert len(rig.meta.inner.paths()) == 1, "the in-flight record was not touched"
        blobs.release.set()
        mine = writer.result(10)
    assert rig.store.read(rig.scope, mine.ref) == b"x"
    assert other.put(rig.scope, rig.new(b"x", attempt=1)) == mine, "the retry gets the committed version back"
    assert len(blobs.keys()) == 1 and len(rig.meta.inner.paths()) == 1


def test_FR_MEM_06_AR_02_a_parent_continuation_never_rewrites_or_orphans_an_in_flight_version(tmp_path):
    rig, blobs, other = _two_stores(tmp_path)
    v1 = rig.put(b"one")
    blobs.hold = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(rig.put, b"two", parent=v1.ref, attempt=2)
        assert blobs.entered.wait(10)
        with pytest.raises(ArtifactBusy):
            other.put(rig.scope, rig.new(b"two", parent=v1.ref, attempt=2))
        v3 = other.put(rig.scope, rig.new(b"three", parent=v1.ref, attempt=3))  # a new key takes the next number
        assert v3.version == 3
        blobs.release.set()
        v2 = writer.result(10)
    assert v2.version == 2
    assert rig.store.read(rig.scope, v2.ref) == b"two" and rig.store.read(rig.scope, v3.ref) == b"three"
    assert [v.version for v in rig.store.versions(rig.scope, v1.artifact_id)] == [1, 2, 3]
    assert blobs.read(blob_key(rig.scope, v2.ref)) == b"two"


def test_FR_MEM_06_AR_05_a_stale_orphan_is_repaired_by_another_store_after_the_grace_window(tmp_path):
    rig, blobs, other = _two_stores(tmp_path)
    blobs.hold = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(rig.put, b"first", attempt=1)
        assert blobs.entered.wait(10)
        rig.clock.advance(GRACE - timedelta(seconds=1))
        with pytest.raises(ArtifactBusy):  # still inside the window
            other.put(rig.scope, rig.new(b"second", attempt=1))
        blobs.release.set()
        writer.result(10)
    # the writer finished, so nothing is orphaned; now make a true orphan: a record whose blob never landed
    (record,) = rig.store.retention().records()
    blobs.delete(blob_key(rig.scope, {"artifact_id": record.record_id.split("/")[5], "version": 1}))
    with pytest.raises(ArtifactBusy):
        other.put(rig.scope, rig.new(b"second", attempt=1))
    rig.clock.advance(timedelta(minutes=10))
    redone = other.put(rig.scope, rig.new(b"second", attempt=1))
    assert redone.version == 1 and other.read(rig.scope, redone.ref) == b"second"
    assert len(blobs.keys()) == 1 and len(rig.meta.inner.paths()) == 1
