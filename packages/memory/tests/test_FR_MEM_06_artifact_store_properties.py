"""FR-MEM-06 property tests (Hypothesis): versions never gap and round-trip their bytes, no other scope ever sees a
version, the world cap is never exceeded, any change to a stored byte is caught, a repeated key never makes a second
version, and an id that is not a whole match never reaches a backend. Sources: contracts/artifact.rules.md AR-01,
AR-02, AR-03, AR-04, AR-05; docs/adr/0018-artifact-output-and-store.md. API: API_FR_MEM_06.md.
`tilo_memory.artifacts` does not exist yet, so these fail at import."""

from __future__ import annotations

import re

import pytest
from _artifact_testlib import (
    MAX_FILE,
    MAX_WORLD,
    OTHER_ORG,
    OTHER_OWNER,
    OTHER_WORLD,
    Sized,
    SizeOnlyBlobs,
    make_rig,
    scope_of,
    sha,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_memory.artifacts import ArtifactCorrupt, ArtifactNotFound, ArtifactRefused, Scope

settings.register_profile("artifacts", deadline=None, max_examples=40)
settings.load_profile("artifacts")

TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=40).filter(
    lambda t: t.strip() != ""
)
OPS = st.lists(st.tuples(st.sampled_from(["new", "next", "restore"]), st.integers(0, 50), TEXT), max_size=25)


@given(ops=OPS)
def test_FR_MEM_06_property_versions_never_gap_and_every_version_round_trips_its_bytes(ops):
    rig = make_rig("memory", None)
    model: dict[str, list[bytes]] = {}
    for kind, pick, text in ops:
        content = text.encode("utf-8")
        ids = sorted(model)
        if kind == "new" or not ids:
            stored = rig.put(content)
            assert stored.version == 1 and stored.record["parents"] == []
            model[stored.artifact_id] = [content]
            continue
        artifact_id = ids[pick % len(ids)]
        target = {"artifact_id": artifact_id, "version": pick % len(model[artifact_id]) + 1}
        if kind == "next":
            stored = rig.put(content, parent=target)
            model[artifact_id].append(content)
        else:
            stored = rig.restore(target)
            model[artifact_id].append(model[artifact_id][target["version"] - 1])
        assert stored.version == len(model[artifact_id]), "the next version is the highest plus one: no gaps"
        assert stored.record["parents"] == [target]
    for artifact_id, contents in model.items():
        listed = rig.store.versions(rig.scope, artifact_id)
        assert [v.version for v in listed] == list(range(1, len(contents) + 1))
        for version, expected in zip(listed, contents, strict=True):
            assert rig.store.read(rig.scope, version.ref) == expected
            assert version.record["content_sha256"] == sha(expected) and version.record["size_bytes"] == len(expected)


@given(texts=st.lists(TEXT, min_size=1, max_size=6))
def test_FR_MEM_06_property_no_other_org_world_or_owner_ever_sees_a_version(texts):
    rig = make_rig("memory", None)
    stored = [rig.put(t.encode("utf-8")) for t in texts]
    for other in (scope_of(org=OTHER_ORG), scope_of(world=OTHER_WORLD), scope_of(owner=OTHER_OWNER)):
        for s in stored:
            assert rig.store.head(other, s.ref) is None
            with pytest.raises(ArtifactNotFound):
                rig.store.read(other, s.ref)
            with pytest.raises(ArtifactNotFound):
                rig.store.versions(other, s.artifact_id)


@given(sizes=st.lists(st.integers(1, MAX_FILE + 10_000_000), max_size=14))
def test_FR_MEM_06_property_a_world_never_holds_more_than_200_000_000_bytes(sizes):
    rig = make_rig("custom", None, blobs=SizeOnlyBlobs())
    total = 0
    for size in sizes:
        hashed = rig.hasher.calls
        should_store = size <= MAX_FILE and total + size <= MAX_WORLD
        if should_store:
            assert rig.upload(Sized(size), "application/pdf").record["size_bytes"] == size
            total += size
        else:
            with pytest.raises(ArtifactRefused):
                rig.upload(Sized(size), "application/pdf")
            assert rig.hasher.calls == hashed, "a refused put is never hashed"
        stored_total = sum(
            v.record["size_bytes"]
            for artifact_id in {k.split("/")[5] for k in rig.blobs.inner.keys()}
            for v in rig.store.versions(rig.scope, artifact_id)
        )
        assert stored_total == total <= MAX_WORLD


@given(content=st.binary(min_size=1, max_size=200), where=st.integers(min_value=0), flip=st.integers(1, 255))
def test_FR_MEM_06_property_changing_any_stored_byte_is_detected_on_read(content, where, flip):
    rig = make_rig("memory", None)
    stored = rig.upload(content, "application/pdf")
    i = where % len(content)
    bad = content[:i] + bytes([content[i] ^ flip]) + content[i + 1 :]
    rig.tamper(stored, bad)
    with pytest.raises(ArtifactCorrupt):
        rig.store.read(rig.scope, stored.ref)
    assert len(rig.alerts) == 1


@given(texts=st.lists(TEXT, min_size=1, max_size=8), attempt=st.integers(1, 9999), index=st.integers(0, 9))
def test_FR_MEM_06_property_a_repeated_idempotency_key_never_makes_a_second_version(texts, attempt, index):
    rig = make_rig("memory", None)
    results = [rig.put(t.encode("utf-8"), attempt=attempt, index=index) for t in texts]
    assert all(r == results[0] for r in results)
    assert len(rig.blobs.inner.keys()) == 1
    assert rig.store.read(rig.scope, results[0].ref) == texts[0].encode("utf-8"), "the first stored bytes win"


_PATTERNS = {
    "org_id": re.compile(r"org_[0-9A-Za-z_]{1,48}"),
    "world_id": re.compile(r"w_[0-9A-Za-z_]{1,48}"),
    "owner": re.compile(r"u_[0-9A-Za-z_]{1,48}"),
}


@given(
    field=st.sampled_from(sorted(_PATTERNS)),
    junk=st.text(max_size=30),
    suffix=st.sampled_from(["", "\n", "/x", "/../y"]),
)
def test_FR_MEM_06_property_an_id_that_is_not_a_whole_match_never_reaches_a_backend(field, junk, suffix):
    rig = make_rig("memory", None)
    prefix = {"org_id": "org_", "world_id": "w_", "owner": "u_"}[field]
    value = prefix + junk + suffix
    if _PATTERNS[field].fullmatch(value):
        return  # a valid id is the other tests' business
    ids = {"org_id": "org_acme", "world_id": "w_alpha", "owner": "u_alice"} | {field: value}
    baseline = (len(rig.meta.calls), len(rig.blobs.calls))
    with pytest.raises(ValueError):
        rig.store.put(Scope(**ids), rig.new(b"content"))
    assert (len(rig.meta.calls), len(rig.blobs.calls)) == baseline


@given(artifact_id=st.text(max_size=30), version=st.integers(-3, 3))
def test_FR_MEM_06_property_a_ref_that_is_not_a_whole_match_never_reaches_a_backend(artifact_id, version):
    rig = make_rig("memory", None)
    if re.fullmatch(r"art_[0-9A-Za-z_]{1,48}", artifact_id) and version >= 1:
        return
    baseline = (len(rig.meta.calls), len(rig.blobs.calls))
    ref = {"artifact_id": artifact_id, "version": version}
    for call in (lambda: rig.store.head(rig.scope, ref), lambda: rig.store.read(rig.scope, ref)):
        with pytest.raises(ValueError):
            call()
    assert (len(rig.meta.calls), len(rig.blobs.calls)) == baseline
