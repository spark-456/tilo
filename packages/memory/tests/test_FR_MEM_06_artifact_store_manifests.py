"""FR-MEM-06 AR-06 (manifest revisions) with MF-01, MF-02, MF-03 and MF-06 at write time. Sources:
contracts/artifact.rules.md AR-06, contracts/manifest.rules.md, contracts/artifact.schema.json
`$defs/manifest_revision`, docs/adr/0018-artifact-output-and-store.md sections 2 and 3, PRD 12.4, 13.3. API:
API_FR_MEM_06.md. MF-04 (events, authz) and MF-05 (skill pin) need the run's events and are `build_manifest`'s, not
the store's. `tilo_memory.artifacts` does not exist yet, so these fail at import."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from _artifact_testlib import (
    ARTICLE,
    CONTRACTS,
    RUN,
    SECRET,
    ULID_A,
    ULID_B,
    Redactor,
    make_manifest,
    make_rig,
    revision_path,
    schema_errors,
)
from tilo_memory.artifacts import ArtifactNotFound, ArtifactRefused, validate_revision

REVISION = ("artifact.schema.json", "#/$defs/manifest_revision")
SRC = {"id": "src_market", "archive_ref": f"{RUN}/7"}


@pytest.fixture(params=["memory", "local"])
def rig(request, tmp_path):
    return make_rig(request.param, tmp_path)


@pytest.fixture
def v1(rig):
    rig.archive.add(rig.scope, SRC["archive_ref"], "the market is 4 billion")
    return rig.put(ARTICLE, sources=(SRC,))


def _add(rig, stored, manifest=None, *, stage="created", cause=None):
    return rig.store.add_manifest(
        rig.scope, stored.ref, make_manifest(stored) if manifest is None else manifest, stage=stage, cause=cause
    )


def _paths(rig):
    return rig.meta.inner.paths()


CLAIM = {
    "id": "cl_market",
    "location": "paragraph/1",
    "text": "The market is 4 billion.",
    "source_ids": ["src_market"],
    "verified": True,
}


def test_FR_MEM_06_AR_06_revisions_are_append_only_numbered_from_1_and_the_latest_wins(rig, v1):
    created = make_manifest(v1, claims=[{**CLAIM, "verified": False}])
    reviewed = make_manifest(v1, claims=[CLAIM])
    assert _add(rig, v1, created, stage="created", cause=None) == 1
    assert _add(rig, v1, reviewed, stage="reviewed", cause=ULID_A) == 2
    assert _add(rig, v1, reviewed, stage="sent", cause=ULID_B) == 3
    assert _add(rig, v1, reviewed, stage="exported", cause=None) == 4

    revisions = rig.store.manifest_revisions(rig.scope, v1.ref)
    assert [r["n"] for r in revisions] == [1, 2, 3, 4]
    assert [r["stage"] for r in revisions] == ["created", "reviewed", "sent", "exported"]
    assert [r["cause"] for r in revisions] == [None, ULID_A, ULID_B, None]
    for revision in revisions:
        assert schema_errors(revision, *REVISION) == []
        validate_revision(revision)
    assert revisions[0]["manifest"]["claims"][0]["verified"] is False, "an earlier revision is never rewritten"
    assert rig.store.manifest(rig.scope, v1.ref) == revisions[-1]["manifest"] == reviewed
    assert [c[1][0] for c in rig.meta.called("create") if "/manifests/" in c[1][0]] == [
        revision_path(rig.scope, v1.ref, n) for n in (1, 2, 3, 4)
    ]


def test_FR_MEM_06_AR_06_a_manifest_names_this_version_and_carries_its_content_sha256(rig, v1):
    v2 = rig.put(b"second", parent=v1.ref)
    other_artifact = {"artifact_id": "art_other", "version": 1}
    bad = {
        "another version of this artifact": make_manifest(v2, artifact={**v2.ref, "version": 1}),
        "version 3 that does not exist": make_manifest(v2, artifact={**v2.ref, "version": 3}),
        "another artifact": make_manifest(v2, artifact=other_artifact),
        "the hash of other bytes": make_manifest(v2, content=b"not the stored bytes"),
        "the previous version's hash": make_manifest(v2, content=ARTICLE),
    }
    for what, manifest in bad.items():
        with pytest.raises(ArtifactRefused):
            _add(rig, v2, manifest)
        assert not [p for p in _paths(rig) if "/manifests/" in p], f"{what}: nothing is stored"
    assert _add(rig, v2, make_manifest(v2)) == 1, "a refused revision uses no number"


def test_FR_MEM_06_AR_06_stage_and_cause_are_bound(rig, v1):
    refused = [
        ("reviewed", None),
        ("sent", None),
        ("bogus", None),
        ("created", "not-a-ulid"),
        ("reviewed", "01jb5vq0000000000000000204"),  # ULIDs are upper case
        ("reviewed", ULID_A + "\n"),
    ]
    for stage, cause in refused:
        with pytest.raises(ArtifactRefused):
            _add(rig, v1, stage=stage, cause=cause)
    assert not [p for p in _paths(rig) if "/manifests/" in p]
    assert _add(rig, v1, stage="created", cause=None) == 1
    assert _add(rig, v1, stage="created", cause=ULID_A) == 2, "created may name the artifact.created event"
    assert _add(rig, v1, stage="reviewed", cause=ULID_B) == 3
    assert _add(rig, v1, stage="exported", cause=None) == 4


@pytest.mark.parametrize(
    "break_it",
    [
        pytest.param(lambda m: m.pop("claims"), id="missing-claims"),
        pytest.param(lambda m: m.update(extra=1), id="unknown-property"),
        pytest.param(lambda m: m.update(v="2.0"), id="wrong-version-tag"),
        pytest.param(lambda m: m.update(content_sha256="AB" * 32), id="upper-case-hash"),
        pytest.param(lambda m: m.update(events=["not-a-ulid"]), id="event-id-not-a-ulid"),
    ],
)
def test_FR_MEM_06_AR_06_a_manifest_that_fails_manifest_schema_is_refused(rig, v1, break_it):
    manifest = make_manifest(v1)
    break_it(manifest)
    with pytest.raises(ArtifactRefused):
        _add(rig, v1, manifest)
    assert not [p for p in _paths(rig) if "/manifests/" in p]


def test_FR_MEM_06_AR_06_MF_01_source_and_claim_ids_are_unique_and_claims_name_real_sources(rig, v1):
    src = make_manifest(v1)["sources"][0]
    cases = {
        "duplicate source id": {"sources": [src, dict(src)]},
        "duplicate claim id": {"claims": [{**CLAIM, "verified": False}, {**CLAIM, "verified": False}]},
        "claim names an unknown source": {"claims": [{**CLAIM, "source_ids": ["src_nowhere"]}]},
        "verified claim with no source": {"claims": [{**CLAIM, "source_ids": []}]},
    }
    for what, override in cases.items():
        with pytest.raises(ArtifactRefused):
            _add(rig, v1, make_manifest(v1, **override))
    assert not [p for p in _paths(rig) if "/manifests/" in p]
    assert _add(rig, v1, make_manifest(v1, claims=[CLAIM])) == 1


def test_FR_MEM_06_AR_06_every_record_source_id_names_a_source_of_the_manifest(rig, v1):
    # ASSUMPTION (AR-06 "sources[].id are unique and name sources of the manifest"): the record's source ids must all
    # appear in the manifest, so the Verifier's {id: archive text} covers the manifest's sources.
    with pytest.raises(ArtifactRefused):
        _add(rig, v1, make_manifest(v1, sources=[]))
    renamed = make_manifest(v1)
    renamed["sources"][0]["id"] = "src_something_else"
    with pytest.raises(ArtifactRefused):
        _add(rig, v1, renamed)
    assert _add(rig, v1) == 1


def test_FR_MEM_06_AR_06_MF_02_parents_are_earlier_versions_of_the_same_artifact(rig, v1):
    v2 = rig.put(b"second", parent=v1.ref)
    for parents in (
        [{"artifact_id": "art_other", "version": 1}],  # another artifact
        [v2.ref],  # itself
        [{**v2.ref, "version": 3}],  # a later version
    ):
        with pytest.raises(ArtifactRefused):
            _add(rig, v2, make_manifest(v2, parents=parents))
    assert _add(rig, v2, make_manifest(v2, parents=[v1.ref])) == 1


def test_FR_MEM_06_AR_06_MF_02_a_restores_manifest_names_the_version_it_restores(rig, v1):
    restored = rig.restore(v1.ref)
    with pytest.raises(ArtifactRefused):
        _add(rig, restored, make_manifest(restored, parents=[]))
    assert _add(rig, restored, make_manifest(restored)) == 1
    assert rig.store.manifest(rig.scope, restored.ref)["parents"] == [v1.ref]
    assert rig.store.manifest(rig.scope, restored.ref)["content_sha256"] == v1.record["content_sha256"]


@pytest.mark.parametrize(
    "ref",
    [
        "https://example.com/report?access_token=abc",
        "https://example.com/report#access_token=abc",
        "https://user:pw@example.com/report",
        "https://example.com/report;access_token=abc",
    ],
)
def test_FR_MEM_06_AR_06_MF_03_a_web_source_ref_with_a_token_shape_is_refused(rig, v1, ref):
    manifest = make_manifest(v1)
    manifest["sources"][0]["ref"] = ref
    with pytest.raises(ArtifactRefused):
        _add(rig, v1, manifest)
    assert not [p for p in _paths(rig) if "/manifests/" in p]


def test_FR_MEM_06_AR_06_MF_06_a_manifest_the_redactor_would_change_is_refused_never_stored(rig, v1):
    manifest = make_manifest(v1, claims=[{**CLAIM, "verified": False, "text": f"The key is {SECRET}"}])
    with pytest.raises(ArtifactRefused) as info:
        _add(rig, v1, manifest)
    assert SECRET not in str(info.value)
    leaky_source = make_manifest(v1)
    leaky_source["sources"][0]["ref"] = f"https://example.com/{SECRET}"
    with pytest.raises(ArtifactRefused):
        _add(rig, v1, leaky_source)
    assert not [p for p in _paths(rig) if "/manifests/" in p]
    assert SECRET not in json.dumps([rig.meta.inner.get(p) for p in _paths(rig)], default=str)


def test_FR_MEM_06_AR_06_MF_06_a_redactor_error_fails_closed(tmp_path):
    rig = make_rig("memory", tmp_path, redactor=Redactor())
    rig.archive.add(rig.scope, SRC["archive_ref"])
    v1 = rig.put(ARTICLE, sources=(SRC,))
    rig.redactor.error = RuntimeError("redactor offline")
    with pytest.raises(ArtifactRefused):
        _add(rig, v1)
    assert not [p for p in _paths(rig) if "/manifests/" in p]


def test_FR_MEM_06_AR_06_the_records_sources_never_appear_in_any_manifest_output(rig, v1):
    _add(rig, v1)
    outputs = [rig.store.manifest(rig.scope, v1.ref), rig.store.manifest_revisions(rig.scope, v1.ref)]
    text = json.dumps(outputs)
    assert "archive_ref" not in text and SRC["archive_ref"] not in text
    leaking = make_manifest(v1)
    leaking["sources"][0]["archive_ref"] = SRC["archive_ref"]
    with pytest.raises(ArtifactRefused):
        _add(rig, v1, leaking)


def test_FR_MEM_06_AR_06_a_manifest_read_back_is_a_copy_so_stored_revisions_cannot_be_edited(rig, v1):
    manifest = make_manifest(v1)
    pristine = copy.deepcopy(manifest)
    _add(rig, v1, manifest)
    manifest["claims"].append({"id": "late"})  # the caller edits its own dict afterwards
    got = rig.store.manifest(rig.scope, v1.ref)
    assert got == pristine
    got["events"].append(ULID_A)
    rig.store.manifest_revisions(rig.scope, v1.ref)[0]["manifest"]["parents"].append(v1.ref)
    assert rig.store.manifest(rig.scope, v1.ref) == pristine


def test_FR_MEM_06_AR_06_no_revision_yet_reads_as_absent(rig, v1):
    with pytest.raises(ArtifactNotFound):
        rig.store.manifest(rig.scope, v1.ref)
    with pytest.raises(ArtifactNotFound):
        rig.store.manifest_revisions(rig.scope, v1.ref)


def test_FR_MEM_06_AR_06_concurrent_revisions_take_distinct_numbers_from_1_without_gaps(rig, v1):
    with ThreadPoolExecutor(max_workers=8) as pool:
        numbers = list(pool.map(lambda _: _add(rig, v1), range(12)))
    assert sorted(numbers) == list(range(1, 13))
    assert [r["n"] for r in rig.store.manifest_revisions(rig.scope, v1.ref)] == list(range(1, 13))


def test_FR_MEM_06_AR_06_each_version_has_its_own_revision_numbers(rig, v1):
    v2 = rig.put(b"second", parent=v1.ref)
    assert _add(rig, v1) == 1 and _add(rig, v1) == 2
    assert _add(rig, v2, make_manifest(v2)) == 1
    assert rig.store.manifest(rig.scope, v2.ref)["artifact"] == v2.ref


def test_FR_MEM_06_validate_revision_is_the_json_schema_valid_and_invalid_fixtures():
    folder = CONTRACTS / "fixtures" / "artifact.manifest_revision"
    valid, invalid = sorted((folder / "valid").glob("*.json")), sorted((folder / "invalid").glob("*.json"))
    assert valid and len(invalid) >= 7
    for path in valid:
        validate_revision(json.loads(path.read_text(encoding="utf-8")))
    for path in invalid:
        with pytest.raises(Exception):  # noqa: B017 - jsonschema.ValidationError or ArtifactRefused
            validate_revision(json.loads(path.read_text(encoding="utf-8")))
