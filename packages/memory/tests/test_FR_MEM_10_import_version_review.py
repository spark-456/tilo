"""FR-MEM-10 security review round 1, the store's half (`ArtifactStore.import_version`; AR-02, AR-03, AR-07, AR-08):

- The result says whether this call stored the version (`written`), so a failed import rolls back only its own.
- A record from after the store's clock is refused (it would never be purged, AR-08).
- Another owner's version at the same path reads as absent (AR-03): its refusal says no more than any other.
- A record without its blob is never purged by an import (another import may still be writing it): ArtifactBusy.
- A restore is an exact copy of the parent the scope holds, and takes that parent's screening (no new verdict).
Fakes only, no network.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from _artifact_testlib import (
    ARTICLE,
    OTHER_ORG,
    OTHER_OWNER,
    OTHER_WORLD,
    FakeSafety,
    blob_key,
    make_rig,
    record_path,
    scope_of,
    sha,
)
from tilo_memory.artifacts import ArtifactBusy, ArtifactRefused, Origin

DEST = scope_of(OTHER_ORG, OTHER_WORLD, OTHER_OWNER)


def carried(rig, stored):
    return dict(stored.record, sources=[]), rig.store.read(rig.scope, stored.ref)


def test_FR_MEM_10_import_version_says_whether_this_call_stored_the_version() -> None:
    a, b = make_rig("memory", None), make_rig("memory", None, scope=DEST)
    record, content = carried(a, a.put(ARTICLE))
    assert b.store.import_version(b.scope, record, content).written is True
    assert b.store.import_version(b.scope, record, content).written is False


def test_FR_MEM_10_a_record_from_after_the_store_s_clock_is_refused() -> None:
    a, b = make_rig("memory", None), make_rig("memory", None, scope=DEST)
    record, content = carried(a, a.put(ARTICLE))
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, dict(record, created_at="9999-12-31T23:59:59.999Z"), content)
    assert b.meta.inner.paths() == [] and b.blobs.inner.keys() == []


def test_FR_MEM_10_another_owner_s_version_at_the_path_is_refused_like_any_other_conflict() -> None:
    a = make_rig("memory", None)
    b = make_rig("memory", None, scope=DEST)
    neighbour = scope_of(OTHER_ORG, OTHER_WORLD, "u_neighbour")
    stored = a.put(ARTICLE)
    record, content = carried(a, stored)
    b.store.import_version(neighbour, record, content)
    with pytest.raises(ArtifactRefused) as theirs:
        b.store.import_version(b.scope, record, content)
    other = b"# Another brief\n"
    mine = make_rig("memory", None, scope=DEST)
    mine.store.import_version(mine.scope, record, content)
    with pytest.raises(ArtifactRefused) as bytes_differ:
        mine.store.import_version(mine.scope, dict(record, content_sha256=sha(other), size_bytes=len(other)), other)
    assert str(theirs.value) == str(bytes_differ.value), "the refusal does not say whose version is there"
    assert b.store.head(b.scope, stored.ref) is None


def test_FR_MEM_10_a_record_without_its_blob_is_never_purged_by_an_import() -> None:
    a, b = make_rig("memory", None), make_rig("memory", None, scope=DEST)
    stored = a.put(ARTICLE)
    record, content = carried(a, stored)
    b.store.import_version(b.scope, record, content)
    b.blobs.inner.delete(blob_key(DEST, stored.ref))  # as if another import is still writing the blob
    b.clock.advance(timedelta(days=2))
    with pytest.raises(ArtifactBusy):
        b.store.import_version(b.scope, record, content)
    assert b.meta.inner.get(record_path(DEST, stored.ref)) is not None, "the record is left for its writer"


def test_FR_MEM_10_a_restore_must_be_an_exact_copy_of_its_parent_and_takes_its_screening() -> None:
    a = make_rig("memory", None)
    v1 = a.put(ARTICLE)
    v2 = a.store.restore(a.scope, v1.ref, by=Origin(kind="restore"))
    safety = FakeSafety(flagged=True)
    b = make_rig("memory", None, scope=DEST, safety=safety)
    b.store.import_version(b.scope, *carried(a, v1))
    restore, content = carried(a, v2)
    forged = b"# Not version 1\n"
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, dict(restore, content_sha256=sha(forged), size_bytes=len(forged)), forged)
    got = b.store.import_version(b.scope, restore, content)
    assert got.record["screening"] == "flagged" and len(safety.calls) == 1, "the parent's verdict, no new one"
