"""FR-MEM-06 AR-03 (scope: ids, absence, sources of the record's own run) and AR-05 (idempotency key, FR-AGT-10).
Sources: contracts/artifact.rules.md AR-03 and AR-05, docs/adr/0018-artifact-output-and-store.md section 3 and the
T1 notes, PRD 15.1, 16.2, 16.5. API: API_FR_MEM_06.md. `tilo_memory.artifacts` does not exist yet, so these fail at
import."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from _artifact_testlib import (
    ARTICLE,
    ORG,
    OTHER_ORG,
    OTHER_OWNER,
    OTHER_WORLD,
    OWNER,
    RUN,
    WORLD,
    make_manifest,
    make_rig,
    outcome,
    scope_of,
)
from tilo_memory.artifacts import ArtifactNotFound, ArtifactRefused, NewVersion, Origin, Scope


@pytest.fixture(params=["memory", "local"])
def rig(request, tmp_path):
    return make_rig(request.param, tmp_path)


OTHER_SCOPES = {
    "other-org": scope_of(org=OTHER_ORG),
    "other-world": scope_of(world=OTHER_WORLD),
    "other-owner": scope_of(owner=OTHER_OWNER),
}


def _baseline(rig):
    return len(rig.meta.calls), len(rig.blobs.calls)


def _untouched(rig, baseline):
    assert (len(rig.meta.calls), len(rig.blobs.calls)) == baseline, "no backend call, so no key or path was derived"


# --- AR-03: ids are checked whole, before any key is derived --------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"org_id": "org_acme/../org_other"},
        {"org_id": "org_acme/"},
        {"org_id": "org_acme\n"},
        {"org_id": ""},
        {"org_id": "acme"},
        {"world_id": "w_alpha\n"},
        {"world_id": "w_alpha/x"},
        {"world_id": "w_"},
        {"owner": "u_alice\n"},
        {"owner": "u_alice/../u_bob"},
        {"owner": "alice"},
    ],
    ids=lambda d: repr(d),
)
def test_FR_MEM_06_AR_03_a_malformed_scope_id_is_refused_before_any_backend_call(rig, bad):
    baseline = _baseline(rig)
    ids = {"org_id": ORG, "world_id": WORLD, "owner": OWNER} | bad
    with pytest.raises(ValueError):
        rig.store.put(Scope(**ids), rig.new(ARTICLE))
    _untouched(rig, baseline)
    assert rig.blobs.inner.keys() == []


@pytest.mark.parametrize(
    "ref",
    [
        {"artifact_id": "art_ok\n", "version": 1},
        {"artifact_id": "art_a/../art_b", "version": 1},
        {"artifact_id": "art_x/y", "version": 1},
        {"artifact_id": "../art_x", "version": 1},
        {"artifact_id": "", "version": 1},
        {"artifact_id": "art_ok", "version": 0},
        {"artifact_id": "art_ok", "version": -1},
    ],
    ids=lambda r: f"{r['artifact_id']!r}@{r['version']}",
)
def test_FR_MEM_06_AR_03_a_malformed_artifact_ref_is_refused_by_every_call_before_any_backend_call(rig, ref):
    stored = rig.put(ARTICLE)
    baseline = _baseline(rig)
    calls = {
        "head": lambda: rig.store.head(rig.scope, ref),
        "read": lambda: rig.store.read(rig.scope, ref),
        "versions": lambda: rig.store.versions(rig.scope, ref["artifact_id"]),
        "restore": lambda: rig.restore(ref),
        "manifest": lambda: rig.store.manifest(rig.scope, ref),
        "manifest_revisions": lambda: rig.store.manifest_revisions(rig.scope, ref),
        "add_manifest": lambda: rig.store.add_manifest(
            rig.scope, ref, make_manifest(stored), stage="created", cause=None
        ),
        "source_texts": lambda: rig.store.source_texts(rig.scope, ref),
        "put-parent": lambda: rig.put(b"child", parent=ref),
    }
    for name, call in calls.items():
        if name == "versions" and ref["version"] < 1:
            continue  # the version is not an argument of `versions`
        with pytest.raises(ValueError):
            call()
        _untouched(rig, baseline)


@pytest.mark.parametrize(
    "override",
    [
        {"run": "r_run1\n"},
        {"run": "r_run1/../r_x"},
        {"key": "r_run1:U1:1:0\n"},
        {"key": "r_run1:U1:1:10"},
        {"key": "r_run1:U1:01:0"},
        {"key": "r_run1:U1:1:0:extra"},
        {"sources": ({"id": "Src_Market", "archive_ref": "r_run1/7"},)},
        {"sources": ({"id": "src_market", "archive_ref": "r_run1/7\n"},)},
        {"sources": ({"id": "src_market", "archive_ref": "r_run1/7/../8"},)},
        {"sources": ({"id": "src_market", "archive_ref": "https://example.com/x"},)},
    ],
    ids=lambda o: repr(o),
)
def test_FR_MEM_06_AR_03_malformed_put_fields_never_reach_a_blob_key(rig, override):
    for ref in ("r_run1/7\n", "r_run1/7/../8", "https://example.com/x"):
        rig.archive.add(rig.scope, ref)  # the archive would answer: only the shape of the ref is at fault
    blob_calls = len(rig.blobs.calls)
    kwargs = {"attempt": 1, "key": "r_run1:U1:1:0", **override}
    with pytest.raises(ArtifactRefused):
        rig.put(ARTICLE, **kwargs)
    assert len(rig.blobs.calls) == blob_calls and rig.meta.called("create") == []


# --- AR-03: another org, world or owner reads as absent, indistinguishably ------------------------


def _operations(rig, stored, scope):
    ref = stored.ref
    return {
        "head": lambda: rig.store.head(scope, ref),
        "read": lambda: rig.store.read(scope, ref),
        "versions": lambda: rig.store.versions(scope, ref["artifact_id"]),
        "restore": lambda: rig.store.restore(scope, ref, by=Origin(kind="restore")),
        "manifest": lambda: rig.store.manifest(scope, ref),
        "manifest_revisions": lambda: rig.store.manifest_revisions(scope, ref),
        "add_manifest": lambda: rig.store.add_manifest(scope, ref, make_manifest(stored), stage="created", cause=None),
        "source_texts": lambda: rig.store.source_texts(scope, ref),
        "put-parent": lambda: rig.store.put(scope, rig.new(b"child", parent=ref)),
    }


@pytest.mark.parametrize("other", list(OTHER_SCOPES), ids=list(OTHER_SCOPES))
def test_FR_MEM_06_AR_03_a_version_of_another_org_world_or_owner_reads_as_absent(rig, other, tmp_path):
    b = OTHER_SCOPES[other]
    v1 = rig.put(ARTICLE)
    v2 = rig.put(b"two", parent=v1.ref)
    rig.store.add_manifest(rig.scope, v2.ref, make_manifest(v2), stage="created", cause=None)
    keys, paths = rig.blobs.inner.keys(), rig.meta.inner.paths()

    assert rig.store.head(b, v2.ref) is None
    for name, call in _operations(rig, v2, b).items():
        if name == "head":
            continue
        with pytest.raises(ArtifactNotFound):
            call()

    # nothing in the owner's scope changed, and nothing was created anywhere
    assert rig.blobs.inner.keys() == keys and rig.meta.inner.paths() == paths
    assert [v.version for v in rig.store.versions(rig.scope, v1.artifact_id)] == [1, 2]
    assert rig.store.read(rig.scope, v2.ref) == b"two"


@pytest.mark.parametrize("other", list(OTHER_SCOPES), ids=list(OTHER_SCOPES))
def test_FR_MEM_06_AR_03_absent_in_scope_is_indistinguishable_from_never_existed(rig, other, tmp_path):
    b = OTHER_SCOPES[other]
    stored = rig.put(ARTICLE)
    rig.store.add_manifest(rig.scope, stored.ref, make_manifest(stored), stage="created", cause=None)
    empty = make_rig("memory", tmp_path / "empty")  # a store in which this ref never existed
    seen = _operations(rig, stored, b)
    never = _operations(empty, stored, b)
    for name in seen:
        assert outcome(seen[name]) == outcome(never[name]), f"{name} tells another scope that the version exists"


def test_FR_MEM_06_AR_03_the_same_artifact_id_is_not_a_namespace_shared_between_scopes(rig):
    a_v1 = rig.put(b"world A", scope=scope_of())
    b = scope_of(world=OTHER_WORLD)
    b_v1 = rig.put(b"world B", scope=b)
    assert a_v1.artifact_id != b_v1.artifact_id
    assert rig.store.read(b, b_v1.ref) == b"world B"
    assert rig.store.head(scope_of(), b_v1.ref) is None
    assert rig.store.head(b, a_v1.ref) is None


# --- AR-03: sources name raw-archive records of the record's own run, org and world ---------------


def test_FR_MEM_06_AR_03_sources_of_the_records_own_run_are_stored_and_read_through_the_scope(rig):
    srcs = ({"id": "src_market", "archive_ref": f"{RUN}/7"}, {"id": "src_rivals", "archive_ref": f"{RUN}/9"})
    rig.archive.add(rig.scope, f"{RUN}/7", "the market is 4 billion")
    rig.archive.add(rig.scope, f"{RUN}/9", "three rivals")
    stored = rig.put(ARTICLE, sources=srcs)
    assert stored.record["sources"] == list(srcs)
    assert rig.archive.calls and all(scope == rig.scope for scope, _ in rig.archive.calls)

    rig.archive.calls.clear()
    assert rig.store.source_texts(rig.scope, stored.ref) == {
        "src_market": "the market is 4 billion",
        "src_rivals": "three rivals",
    }
    assert {ref for _, ref in rig.archive.calls} == {f"{RUN}/7", f"{RUN}/9"}
    assert all(scope == rig.scope for scope, _ in rig.archive.calls), "archive reads go through the version's Scope"


def test_FR_MEM_06_AR_03_a_source_record_absent_in_the_scope_is_not_served_from_another_world(rig):
    rig.archive.add(rig.scope, f"{RUN}/7", "only in this world")
    stored = rig.put(ARTICLE, sources=({"id": "src_market", "archive_ref": f"{RUN}/7"},))
    rig.archive.remove(rig.scope, f"{RUN}/7")
    rig.archive.add(scope_of(world=OTHER_WORLD), f"{RUN}/7", "another world's record under the same ref")
    with pytest.raises(ArtifactNotFound):
        rig.store.source_texts(rig.scope, stored.ref)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("another-run", id="archive_ref-of-another-run"),
        pytest.param("not-in-archive", id="archive-has-no-such-record"),
        pytest.param("other-world", id="record-exists-only-in-another-world"),
        pytest.param("other-org", id="record-exists-only-in-another-org"),
    ],
)
def test_FR_MEM_06_AR_03_a_source_that_is_not_a_record_of_the_run_org_and_world_is_refused(rig, case):
    ref = f"{RUN}/7"
    if case == "another-run":
        ref = "r_otherrun/7"
        rig.archive.add(rig.scope, ref)  # the archive answers, but the run is not the record's own
    elif case == "other-world":
        rig.archive.add(scope_of(world=OTHER_WORLD), ref)
    elif case == "other-org":
        rig.archive.add(scope_of(org=OTHER_ORG), ref)
    with pytest.raises(ArtifactRefused):
        rig.put(ARTICLE, sources=({"id": "src_market", "archive_ref": ref},))
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


def test_FR_MEM_06_AR_03_duplicate_source_ids_and_upload_sources_are_refused(rig):
    rig.archive.add(rig.scope, f"{RUN}/7")
    rig.archive.add(rig.scope, f"{RUN}/9")
    twice = ({"id": "src_market", "archive_ref": f"{RUN}/7"}, {"id": "src_market", "archive_ref": f"{RUN}/9"})
    with pytest.raises(ArtifactRefused):
        rig.put(ARTICLE, sources=twice)
    upload = NewVersion(
        media_type="text/markdown",
        content=ARTICLE,
        run_id=RUN,
        origin=Origin(kind="upload"),
        sources=({"id": "src_market", "archive_ref": f"{RUN}/7"},),
    )
    with pytest.raises(ArtifactRefused):
        rig.store.put(rig.scope, upload)
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


# --- AR-05: one version per idempotency key (FR-AGT-10) -------------------------------------------


def test_FR_MEM_06_AR_05_FR_AGT_10_a_restarted_unit_gets_the_same_version_back(rig):
    first = rig.put(ARTICLE, attempt=1, index=0)
    again = rig.put(ARTICLE, attempt=1, index=0)
    assert again == first
    assert again.record["idempotency_key"] == f"{RUN}:U1:1:0"
    assert len(rig.blobs.inner.keys()) == 1
    assert [v.version for v in rig.store.versions(rig.scope, first.artifact_id)] == [1], "no new version"


def test_FR_MEM_06_AR_05_the_first_stored_bytes_win_and_nothing_is_rewritten(rig):
    # ASSUMPTION (FR-AGT-10, PRD 11): a restart that produces other bytes still gets the first version back.
    first = rig.put(b"first attempt output", attempt=1)
    again = rig.put(b"a different output on restart", attempt=1)
    assert again == first
    assert rig.store.read(rig.scope, first.ref) == b"first attempt output"
    assert len(rig.blobs.inner.keys()) == 1


def test_FR_MEM_06_AR_05_outputs_of_one_unit_with_different_index_or_attempt_are_different_artifacts(rig):
    a = rig.put(b"zero", attempt=1, index=0)
    b = rig.put(b"one", attempt=1, index=1)
    c = rig.put(b"retry", attempt=2, index=0)
    assert len({a.artifact_id, b.artifact_id, c.artifact_id}) == 3
    assert {a.version, b.version, c.version} == {1}


def test_FR_MEM_06_AR_05_the_key_must_name_the_records_own_run_and_unit(rig):
    with pytest.raises(ArtifactRefused):
        rig.put(ARTICLE, run="r_run1", unit="U1", key="r_otherrun:U1:1:0")
    with pytest.raises(ArtifactRefused):
        rig.put(ARTICLE, run="r_run1", unit="U1", key="r_run1:U2:1:0")
    with pytest.raises(ArtifactRefused):
        rig.put(ARTICLE, run="r_run1", unit="U1", key=None)  # unit and render outputs always have a key (schema)
    assert rig.blobs.inner.keys() == []


@pytest.mark.parametrize("other", list(OTHER_SCOPES), ids=list(OTHER_SCOPES))
def test_FR_MEM_06_AR_05_the_key_lookup_is_inside_the_scope_so_another_scopes_key_is_absent(rig, other):
    b = OTHER_SCOPES[other]
    mine = rig.put(b"mine", attempt=1)
    theirs = rig.put(b"theirs", attempt=1, scope=b)  # the same key string, in another org, world or owner
    assert theirs.record["world_id"] == b.world_id and theirs.record["org_id"] == b.org_id
    assert theirs.record["owner"] == b.owner
    assert (theirs.artifact_id, theirs.version) != (mine.artifact_id, mine.version)
    assert rig.store.read(b, theirs.ref) == b"theirs"
    assert rig.store.read(rig.scope, mine.ref) == b"mine"
    # a repeat in either scope returns that scope's own version
    assert rig.put(b"mine", attempt=1) == mine
    assert rig.put(b"theirs", attempt=1, scope=b) == theirs


def test_FR_MEM_06_AR_05_uploads_and_restores_have_no_key(rig):
    with pytest.raises(ArtifactRefused):
        rig.store.put(
            rig.scope,
            NewVersion(
                media_type="text/markdown",
                content=ARTICLE,
                run_id=RUN,
                origin=Origin(kind="upload"),
                idempotency_key=f"{RUN}:U1:1:0",
            ),
        )
    upload = rig.upload(ARTICLE)
    assert upload.record["idempotency_key"] is None
    assert rig.upload(ARTICLE).artifact_id != upload.artifact_id, "no key, so every upload is a new artifact"
    assert rig.restore(upload.ref).record["idempotency_key"] is None


def test_FR_MEM_06_AR_05_the_same_key_from_many_threads_makes_one_version(rig):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: rig.put(ARTICLE, attempt=1, index=0), range(16)))
    assert all(r == results[0] for r in results)
    assert len(rig.blobs.inner.keys()) == 1


def test_FR_MEM_06_AR_02_concurrent_puts_to_one_artifact_take_distinct_gapless_versions(rig):
    v1 = rig.put(b"base")
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(lambda n: rig.put(f"edit {n}".encode(), parent=v1.ref), range(12)))
    assert sorted(v.version for v in got) == list(range(2, 14))
    assert [v.version for v in rig.store.versions(rig.scope, v1.artifact_id)] == list(range(1, 14))
    for v in got:
        assert v.record["parents"] == [v1.ref]
