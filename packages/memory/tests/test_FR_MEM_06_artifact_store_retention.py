"""FR-MEM-06 AR-08 with FR-MEM-09: the artifact store's retention adapter (entity `artifact`, 90 days, user_id is the
owner), registered as `gcs_artifacts` in the erasure registry. Sources: contracts/artifact.rules.md AR-08,
docs/adr/0018-artifact-output-and- store.md sections 2, 3 and 8 (T8), PRD 15.1, 16.5,
`packages/memory/src/tilo_memory/{retention,erasure}.py`. API: API_FR_MEM_06.md. `tilo_memory.artifacts` does not
exist yet, so these fail at import."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from _artifact_testlib import ARTICLE, OTHER_OWNER, OWNER, T0, blob_key, make_manifest, make_rig, scope_of
from _memory_lib import build_registry
from tilo_memory.artifacts import ArtifactNotFound
from tilo_memory.erasure import REQUIRED_STORES, erase_user, request_erasure, verify_erasure
from tilo_memory.retention import RETENTION_DAYS, purge_expired

DAY = timedelta(days=1)


@pytest.fixture(params=["memory", "local"])
def rig(request, tmp_path):
    return make_rig(request.param, tmp_path)


def _registry(store):
    registry = build_registry(sorted(REQUIRED_STORES))
    registry["gcs_artifacts"] = store.retention()
    return registry


def _is_gone(rig, stored, scope=None):
    scope = scope or rig.scope
    assert rig.store.head(scope, stored.ref) is None
    assert blob_key(scope, stored.ref) not in rig.blobs.inner.keys()
    assert [p for p in rig.meta.inner.paths() if f"/{stored.artifact_id}/" in p and f"/{stored.version:06d}" in p] == []
    with pytest.raises(ArtifactNotFound):
        rig.store.read(scope, stored.ref)
    with pytest.raises(ArtifactNotFound):
        rig.store.manifest(scope, stored.ref)


def test_FR_MEM_06_AR_08_the_retention_window_for_an_artifact_is_90_days():
    assert RETENTION_DAYS["artifact"] == 90


def test_FR_MEM_06_AR_08_the_adapter_reports_one_artifact_record_per_version_owned_by_the_owner(rig):
    v1 = rig.put(ARTICLE)
    rig.clock.advance(DAY)
    v2 = rig.put(b"second", parent=v1.ref)
    bobs = scope_of(owner=OTHER_OWNER)
    v3 = rig.put(b"bob's", scope=bobs)
    other_world = rig.put(b"elsewhere", scope=scope_of(world="w_beta"))

    records = list(rig.store.retention().records())

    assert len(records) == 4
    assert {r.entity for r in records} == {"artifact"}
    assert len({r.record_id for r in records}) == 4, "record_id is unique within the store"
    by_owner = sorted((r.user_id, r.created_at) for r in records)
    assert by_owner == sorted([(OWNER, T0), (OWNER, T0 + DAY), (OTHER_OWNER, T0 + DAY), (OWNER, T0 + DAY)])
    assert all(r.created_at.tzinfo is not None and r.created_at.utcoffset() == timedelta(0) for r in records)
    assert "Market brief" not in repr(records), "a record never carries content"
    assert {v1.version, v2.version, v3.version, other_world.version} == {1, 2}


def test_FR_MEM_06_AR_08_a_fresh_read_every_time_and_delete_is_idempotent(rig):
    stored = rig.put(ARTICLE)
    adapter = rig.store.retention()
    (record,) = adapter.records()
    adapter.delete(record.record_id)
    adapter.delete(record.record_id)  # idempotent
    adapter.delete("no-such-record")  # an unknown id is not an error
    assert list(adapter.records()) == []
    _is_gone(rig, stored)


def test_FR_MEM_06_AR_08_delete_removes_every_blob_the_record_and_its_manifests(rig):
    stored = rig.put(ARTICLE)
    for _ in range(3):
        rig.store.add_manifest(rig.scope, stored.ref, make_manifest(stored), stage="created", cause=None)
    adapter = rig.store.retention()
    (doomed,) = adapter.records()
    keep = rig.put(b"another artifact")

    adapter.delete(doomed.record_id)

    _is_gone(rig, stored)
    assert rig.store.read(rig.scope, keep.ref) == b"another artifact", "only the deleted version is touched"
    assert [r.record_id for r in adapter.records()] != [doomed.record_id]


def test_FR_MEM_06_AR_08_delete_removes_every_generation_of_the_blob(tmp_path):
    class GenerationalBlobs:
        """A bucket with object versioning on: create adds a generation, delete removes all of them."""

        def __init__(self):
            self.generations: dict[str, list[bytes]] = {}

        def create(self, key, data):
            if self.generations.get(key):
                raise FileExistsError(key)
            self.generations[key] = [data]

        def read(self, key):
            try:
                return self.generations[key][-1]
            except (KeyError, IndexError):
                raise FileNotFoundError(key) from None

        def delete(self, key):
            self.generations.pop(key, None)

        def keys(self, prefix=""):
            return sorted(k for k in self.generations if k.startswith(prefix))

    blobs = GenerationalBlobs()
    rig = make_rig("custom", tmp_path, blobs=blobs)
    stored = rig.put(ARTICLE)
    blobs.generations[blob_key(rig.scope, stored.ref)].insert(0, b"an older generation of the same object")
    (record,) = rig.store.retention().records()
    rig.store.retention().delete(record.record_id)
    assert blobs.generations == {}, "no generation of the object is left"


def test_FR_MEM_06_AR_08_purge_expired_removes_a_version_strictly_older_than_90_days(rig):
    stored = rig.put(ARTICLE)
    rig.store.add_manifest(rig.scope, stored.ref, make_manifest(stored), stage="created", cause=None)
    registry = {"gcs_artifacts": rig.store.retention()}

    assert purge_expired(registry, now=T0 + 90 * DAY) == {"gcs_artifacts": 0}, "exactly 90 days old is kept (BQ-196)"
    assert rig.store.read(rig.scope, stored.ref) == ARTICLE
    assert purge_expired(registry, now=T0 + 90 * DAY + timedelta(seconds=1)) == {"gcs_artifacts": 1}
    _is_gone(rig, stored)
    assert rig.meta.inner.paths() == [] and rig.blobs.inner.keys() == []


def test_FR_MEM_06_AR_08_purge_is_per_version_so_a_newer_version_outlives_an_older_one(rig):
    v1 = rig.put(b"old draft")
    rig.clock.advance(60 * DAY)
    v2 = rig.put(b"new draft", parent=v1.ref)
    registry = {"gcs_artifacts": rig.store.retention()}

    assert purge_expired(registry, now=T0 + 91 * DAY) == {"gcs_artifacts": 1}
    _is_gone(rig, v1)
    assert rig.store.read(rig.scope, v2.ref) == b"new draft"
    assert [v.version for v in rig.store.versions(rig.scope, v2.artifact_id)] == [2]

    assert purge_expired(registry, now=T0 + 151 * DAY) == {"gcs_artifacts": 1}
    _is_gone(rig, v2)


def test_FR_MEM_06_AR_08_FR_MEM_09_artifacts_are_registered_as_gcs_artifacts_and_erased_per_user(rig):
    assert "gcs_artifacts" in REQUIRED_STORES
    alice = [rig.put(f"alice {n}".encode()) for n in range(2)]
    alice.append(rig.put(b"alice 2", parent=alice[0].ref))
    rig.store.add_manifest(rig.scope, alice[0].ref, make_manifest(alice[0]), stage="created", cause=None)
    bobs = scope_of(owner=OTHER_OWNER)
    bob = rig.put(b"bob", scope=bobs)
    registry = _registry(rig.store)
    now = datetime(2026, 10, 6, tzinfo=UTC)

    before = verify_erasure(registry, OWNER)
    assert before.ok is False and before.remaining["gcs_artifacts"] == 3
    assert len(rig.blobs.inner.keys()) == 4, "verify is read-only"

    report = erase_user(registry, request_erasure(OWNER, requested_at=now), now=now)

    assert report.complete is True and report.failures == {}
    assert report.removed["gcs_artifacts"] == 3 and report.remaining["gcs_artifacts"] == 0
    for stored in alice:
        _is_gone(rig, stored)
    assert rig.store.read(bobs, bob.ref) == b"bob", "another user's artifacts are never touched"
    assert verify_erasure(registry, OWNER).ok is True
    assert verify_erasure(registry, OTHER_OWNER).remaining["gcs_artifacts"] == 1
    assert rig.blobs.inner.keys() == [blob_key(bobs, bob.ref)]
    assert not any(a.artifact_id in p for a in alice for p in rig.meta.inner.paths()), "no trace of the erased user"
