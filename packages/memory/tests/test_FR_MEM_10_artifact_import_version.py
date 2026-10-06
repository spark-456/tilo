"""FR-MEM-10 (PRD 13.4 "any run can be exported as a bundle ... for incident review", 13.5 "Export and re-import a run;
replay is identical"): the artifact store's half of the re-import, `ArtifactStore.import_version`.

Why the store needs its own entry point: `put` mints the artifact id, the version, the hash and the screening verdict
itself (a keyword for them is a `TypeError`, AR-02, AR-07), so a bundle cannot be replayed with `put` and still give the
same ids, versions, bytes and `created` times that the run's events name (EV-15). `import_version` places one version
from an untrusted bundle under the IMPORTER's Scope. Interface (API_FR_MEM_10.md in services/harness/tests):

    ArtifactStore.import_version(scope: Scope, record: dict, content: bytes) -> StoredVersion

The rules pinned here, from contracts/artifact.rules.md:
- AR-03: the Scope is the importer's. The record's `org_id`, `world_id` and `owner` are overwritten from it, so a record
  that names another scope is stored under the importer's and nothing under the named one.
- AR-06: the record's `sources` never leave Tilo, so an imported record has `sources == []` whatever it carries.
- AR-01: `content_sha256` and `size_bytes` must match the bytes (hashed with the store's hasher); a mismatch stores
  nothing.
- AR-02: versions are gapless: version 1 has no parent, version n continues an earlier version of the same id that the
  Scope already holds. The same (id, version) again with the same hash is the same version (idempotent), with another
  hash it is refused and never overwritten.
- AR-04: kinds and caps are checked before hashing, the world's 200,000,000 bytes included.
- AR-05: the idempotency key is kept; a key already held by another version is refused.
- AR-07: text and JSON must survive the importer's redactor unchanged (a secret in a bundle is refused, never stored or
  silently redacted: the bytes would no longer match the hash), `redacted` is kept, and screening is the IMPORTER's:
  a `clean` claim is never copied (the importer's screener judges the exact bytes, and without a verdict it is
  `unscreened`), `unscreened` and `flagged` stay as they are and the screener is not asked about them.
- The record is validated against contracts/artifact.schema.json after the rewrite; any refusal raises `ArtifactRefused`
  and stores no blob, no record and uses no version number.

`tilo_memory.artifacts.ArtifactStore.import_version` does not exist yet, so every test fails with an AttributeError.
That is the right failure. Hypothesis property at the end. Fakes only, no network.

"""

from __future__ import annotations

import json
import string
from datetime import timedelta

import pytest
from _artifact_testlib import (
    ARTICLE,
    JSON_DOC,
    MB,
    ORG,
    OTHER_ORG,
    OTHER_OWNER,
    OTHER_WORLD,
    OWNER,
    RUN,
    SECRET,
    WORLD,
    Clock,
    FakeSafety,
    Sized,
    SizeOnlyBlobs,
    iso,
    make_rig,
    scope_of,
    sha,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_memory.artifacts import ArtifactRefused, MemoryBlobBackend, Scope

settings.register_profile("artifact_import", deadline=None, max_examples=40)
settings.load_profile("artifact_import")

DEST = scope_of(OTHER_ORG, OTHER_WORLD, OTHER_OWNER)
VICTIM = scope_of("org_victim", "w_victim", "u_victim")


def source(**kw):
    return make_rig("memory", None, **kw)


def dest(**kw):
    return make_rig("memory", None, scope=DEST, **kw)


def carried(rig, stored):
    """What a bundle carries for one version: the store's record with `sources` emptied (AR-06), and the bytes."""
    return dict(stored.record, sources=[]), rig.store.read(rig.scope, stored.ref)


def forge(record, content):
    """A record that is consistent with `content` (size and hash), so only the rule under test can refuse it."""
    return dict(record, size_bytes=len(content), content_sha256=sha(bytes(content)))


def empty(rig) -> bool:
    return rig.meta.inner.paths() == [] and rig.blobs.inner.keys() == []


def put_v1(rig, content=ARTICLE):
    stored = rig.put(content)
    return stored, *carried(rig, stored)


# --- what is placed: ids, bytes, hash, the importer's scope --------------------------------------------------------


def test_FR_MEM_10_import_version_keeps_ids_bytes_and_hash_and_takes_the_importer_scope() -> None:
    a, b = source(), dest()
    a.archive.add(a.scope, f"{RUN}/1")
    v1 = a.put(ARTICLE, sources=({"id": "src_a", "archive_ref": f"{RUN}/1"},))
    v2 = a.put(b"# Market brief v2\n", parent=v1.ref)
    for stored in (v1, v2):
        record, content = carried(a, stored)
        got = b.store.import_version(b.scope, record, content)
        assert got.ref == stored.ref and got.artifact_id == stored.artifact_id and got.version == stored.version
        expected = dict(
            stored.record, org_id=DEST.org_id, world_id=DEST.world_id, owner=DEST.owner, sources=[], screened_at=None
        )
        assert dict(got.record, screened_at=None) == expected, (
            "the same record, in the importer's scope, without sources"
        )
        assert b.store.read(b.scope, stored.ref) == a.store.read(a.scope, stored.ref)
        assert got.record["content_sha256"] == sha(a.store.read(a.scope, stored.ref))
    assert [v.version for v in b.store.versions(b.scope, v1.artifact_id)] == [1, 2]
    for needle in (ORG, WORLD, OWNER):
        assert not b.meta.mentions(needle) and not b.blobs.mentions(needle), f"{needle} reached the importer's store"
    assert b.store.head(a.scope, v1.ref) is None, "the source scope's identity is never reused"


def test_FR_MEM_10_a_record_naming_another_scope_is_stored_under_the_importer_scope_only() -> None:
    a, b = source(), dest()
    stored, record, content = put_v1(a)
    record |= {"org_id": VICTIM.org_id, "world_id": VICTIM.world_id, "owner": VICTIM.owner}
    got = b.store.import_version(b.scope, record, content)
    assert (got.record["org_id"], got.record["world_id"], got.record["owner"]) == (
        DEST.org_id,
        DEST.world_id,
        DEST.owner,
    )
    for needle in ("org_victim", "w_victim", "u_victim"):
        assert not b.meta.mentions(needle) and not b.blobs.mentions(needle)
    assert b.store.head(VICTIM, stored.ref) is None
    assert all(p.startswith(f"orgs/{DEST.org_id}/worlds/{DEST.world_id}/") for p in b.meta.inner.paths())


def test_FR_MEM_10_a_bad_scope_is_refused_before_any_backend_call() -> None:
    a, b = source(), dest()
    _stored, record, content = put_v1(a)
    with pytest.raises(ValueError):
        b.store.import_version(Scope(org_id="org_x/../y", world_id=DEST.world_id, owner=DEST.owner), record, content)
    assert b.meta.calls == [] and b.blobs.calls == []


def test_FR_MEM_10_the_record_s_sources_never_enter_the_importer_store() -> None:
    a, b = source(), dest()
    a.archive.add(a.scope, f"{RUN}/7")
    stored = a.put(ARTICLE, sources=({"id": "src_a", "archive_ref": f"{RUN}/7"},))
    record, content = dict(stored.record), a.store.read(a.scope, stored.ref)
    assert record["sources"], "the source record carries a source"
    got = b.store.import_version(b.scope, record, content)  # even a bundle that kept them
    assert got.record["sources"] == [] and not b.meta.mentions(f"{RUN}/7")


# --- integrity: hash, size, schema ---------------------------------------------------------------------------------


def test_FR_MEM_10_altered_bytes_are_refused_and_store_nothing() -> None:
    a, b = source(), dest()
    _stored, record, content = put_v1(a)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, record, content + b"!")
    assert empty(b)


def test_FR_MEM_10_a_size_that_does_not_match_the_bytes_is_refused() -> None:
    a, b = source(), dest()
    _stored, record, content = put_v1(a)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, dict(record, size_bytes=record["size_bytes"] + 1), content)
    assert empty(b)


MUTATIONS = {
    "unknown_key": lambda r: dict(r, extra="x"),
    "missing_key": lambda r: {k: v for k, v in r.items() if k != "created_at"},
    "wrong_version_tag": lambda r: dict(r, v="2.0"),
    "media_type_not_allowed": lambda r: dict(r, media_type="text/html"),
    "two_parents": lambda r: dict(r, parents=[r["artifact"], r["artifact"]]),
    "unknown_screening": lambda r: dict(r, screening="maybe"),
    "unknown_origin_kind": lambda r: dict(r, origin={"kind": "hacker", "unit": None, "agent": None}),
    "bad_timestamp": lambda r: dict(r, created_at="yesterday"),
    "uppercase_hash": lambda r: dict(r, content_sha256=r["content_sha256"].upper()),
    "artifact_id_with_slashes": lambda r: dict(r, artifact={"artifact_id": "art_x/../y", "version": 1}),
    "artifact_id_with_newline": lambda r: dict(
        r, artifact={"artifact_id": r["artifact"]["artifact_id"] + "\n", "version": 1}
    ),
    "version_zero": lambda r: dict(r, artifact={"artifact_id": r["artifact"]["artifact_id"], "version": 0}),
    "bad_run_id": lambda r: dict(r, run_id="not-a-run"),
    "unit_key_without_unit": lambda r: dict(r, idempotency_key=None),
    "upload_with_a_key": lambda r: dict(r, origin={"kind": "upload", "unit": None, "agent": None}),
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_FR_MEM_10_a_record_that_breaks_the_artifact_schema_is_refused_and_stores_nothing(name) -> None:
    a, b = source(), dest()
    _stored, record, content = put_v1(a)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, MUTATIONS[name](record), content)
    assert empty(b)


def test_FR_MEM_10_a_record_that_is_not_an_object_is_refused() -> None:
    a, b = source(), dest()
    _stored, _record, content = put_v1(a)
    for bad in (None, [], "record", 7):
        with pytest.raises(ArtifactRefused):
            b.store.import_version(b.scope, bad, content)  # type: ignore[arg-type]
    assert empty(b)


# --- AR-02 ordering, idempotency, AR-05 keys -----------------------------------------------------------------------


def test_FR_MEM_10_versions_are_gapless_and_each_continues_an_earlier_version() -> None:
    a, b = source(), dest()
    v1 = a.put(ARTICLE)
    v2 = a.put(b"two\n", parent=v1.ref)
    v3 = a.put(b"three\n", parent=v2.ref)
    r2, c2 = carried(a, v2)
    r3, c3 = carried(a, v3)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, r2, c2)  # version 2 before version 1
    assert empty(b)
    b.store.import_version(b.scope, *carried(a, v1))
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, r3, c3)  # version 3 skips version 2
    assert [v.version for v in b.store.versions(b.scope, v1.artifact_id)] == [1]


def test_FR_MEM_10_parents_are_empty_for_version_1_and_one_earlier_version_after() -> None:
    a, b = source(), dest()
    v1 = a.put(ARTICLE)
    v2 = a.put(b"two\n", parent=v1.ref)
    r1, c1 = carried(a, v1)
    r2, c2 = carried(a, v2)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, dict(r1, parents=[v2.ref]), c1)
    assert empty(b)
    b.store.import_version(b.scope, r1, c1)
    for bad in ([], [{"artifact_id": v1.artifact_id, "version": 5}], [{"artifact_id": "art_other", "version": 1}]):
        with pytest.raises(ArtifactRefused):
            b.store.import_version(b.scope, dict(r2, parents=bad), c2)
    assert [v.version for v in b.store.versions(b.scope, v1.artifact_id)] == [1]


def test_FR_MEM_10_the_same_version_again_is_the_same_version_and_writes_nothing() -> None:
    a, b = source(), dest()
    stored, record, content = put_v1(a)
    first = b.store.import_version(b.scope, record, content)
    before = (b.meta.inner.paths(), b.blobs.inner.keys(), len(b.meta.called("create")), len(b.blobs.called("create")))
    again = b.store.import_version(b.scope, record, content)
    assert again.record == first.record and again.ref == stored.ref
    assert (
        b.meta.inner.paths(),
        b.blobs.inner.keys(),
        len(b.meta.called("create")),
        len(b.blobs.called("create")),
    ) == before


def test_FR_MEM_10_the_same_version_with_other_bytes_is_refused_and_never_overwritten() -> None:
    a, b = source(), dest()
    stored, record, content = put_v1(a)
    b.store.import_version(b.scope, record, content)
    other = b"# Another brief\n"
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, forge(record, other), other)
    assert b.store.read(b.scope, stored.ref) == content


def test_FR_MEM_10_an_idempotency_key_held_by_another_version_is_refused() -> None:
    a, b = source(), dest()
    first = a.put(ARTICLE, key=f"{RUN}:U1:1:0")
    second = a.put(b"# Other\n", key=f"{RUN}:U1:2:0")
    r1, c1 = carried(a, first)
    r2, c2 = carried(a, second)
    kept = b.store.import_version(b.scope, r1, c1)
    assert kept.record["idempotency_key"] == f"{RUN}:U1:1:0", "the key is kept (AR-05)"
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, dict(r2, idempotency_key=r1["idempotency_key"]), c2)
    assert [v.artifact_id for v in b.store.versions(b.scope, kept.artifact_id)] == [kept.artifact_id]
    assert b.store.head(b.scope, second.ref) is None


# --- AR-07: secrets and screening ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("media", "body"),
    [
        ("text/markdown", ARTICLE + SECRET.encode()),
        ("application/json", json.dumps({"note": SECRET}).encode()),
        ("text/csv", b"item,price\n" + SECRET.encode() + b",4\n"),
    ],
)
def test_FR_MEM_10_text_the_redactor_would_change_is_refused_never_stored_or_silently_redacted(media, body) -> None:
    a, b = source(), dest()
    stored = a.put(
        {"text/markdown": ARTICLE, "application/json": JSON_DOC, "text/csv": b"item,price\nbolt,4\n"}[media],
        media_type=media,
    )
    record, _ = carried(a, stored)
    with pytest.raises(ArtifactRefused) as caught:
        b.store.import_version(b.scope, forge(record, body), body)
    assert SECRET not in str(caught.value), "the refusal never repeats the secret"
    assert empty(b) and not b.meta.mentions(SECRET) and not b.blobs.mentions(SECRET)


def test_FR_MEM_10_a_redacted_version_stays_redacted_and_the_secret_never_comes_back() -> None:
    a, b = source(), dest()
    stored = a.put(ARTICLE + SECRET.encode())
    record, content = carried(a, stored)
    assert record["redacted"] is True and SECRET.encode() not in content
    got = b.store.import_version(b.scope, record, content)
    assert got.record["redacted"] is True
    assert b.store.read(b.scope, stored.ref) == content and b"[REDACTED]" in content
    assert not b.meta.mentions(SECRET) and not b.blobs.mentions(SECRET)


def test_FR_MEM_10_a_redactor_error_fails_the_import_closed() -> None:
    from _artifact_testlib import Redactor

    a, b = source(), dest(redactor=Redactor(error=RuntimeError("down")))
    _stored, record, content = put_v1(a)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, record, content)
    assert empty(b)


def test_FR_MEM_10_a_clean_claim_is_never_copied_without_a_verdict_it_is_unscreened() -> None:
    a, b = source(), dest(safety=None)
    _stored, record, content = put_v1(a)
    assert record["screening"] == "clean"
    got = b.store.import_version(b.scope, record, content)
    assert (got.record["screening"], got.record["screened_at"]) == ("unscreened", None)


def test_FR_MEM_10_a_clean_claim_is_judged_again_on_the_exact_bytes_by_the_importer_s_screener() -> None:
    clock = Clock()
    safety = FakeSafety()
    a, b = source(), dest(safety=safety, clock=clock)
    _stored, record, content = put_v1(a)
    clock.advance(timedelta(hours=1))
    got = b.store.import_version(b.scope, record, content)
    assert [c["text"] for c in safety.calls] == [content.decode("utf-8")], "the screener saw the exact stored bytes"
    assert got.record["screening"] == "clean"
    assert got.record["screened_at"] == iso(clock.now), "the verdict's time is the importer's, not the bundle's"


def test_FR_MEM_10_a_flagged_verdict_on_a_clean_claim_makes_it_flagged() -> None:
    a, b = source(), dest(safety=FakeSafety(flagged=True))
    _stored, record, content = put_v1(a)
    got = b.store.import_version(b.scope, record, content)
    assert got.record["screening"] == "flagged" and got.record["screened_at"] is not None


@pytest.mark.parametrize(
    "failure", [FakeSafety(error=TimeoutError("slow")), FakeSafety(result="ok"), FakeSafety(result=None)]
)
def test_FR_MEM_10_no_verdict_on_a_clean_claim_is_unscreened_never_clean(failure) -> None:
    a, b = source(), dest(safety=failure)
    _stored, record, content = put_v1(a)
    got = b.store.import_version(b.scope, record, content)
    assert (got.record["screening"], got.record["screened_at"]) == ("unscreened", None)


def test_FR_MEM_10_an_unscreened_version_stays_unscreened_and_is_not_screened_again() -> None:
    a = source(safety=FakeSafety(error=TimeoutError("slow")))
    safety = FakeSafety()  # the importer's screener would say clean
    b = dest(safety=safety)
    _stored, record, content = put_v1(a)
    assert (record["screening"], record["screened_at"]) == ("unscreened", None)
    got = b.store.import_version(b.scope, record, content)
    assert (got.record["screening"], got.record["screened_at"]) == ("unscreened", None)
    assert safety.calls == [], "AR-07: only a verdict on the exact bytes makes a version clean; none was asked for"


def test_FR_MEM_10_a_flagged_version_stays_flagged_even_if_the_importer_s_screener_says_clean() -> None:
    a = source(safety=FakeSafety(flagged=True))
    safety = FakeSafety()
    b = dest(safety=safety)
    _stored, record, content = put_v1(a)
    assert record["screening"] == "flagged"
    got = b.store.import_version(b.scope, record, content)
    assert got.record["screening"] == "flagged" and got.record["screened_at"] == record["screened_at"]
    assert safety.calls == []


def test_FR_MEM_10_a_file_clean_claim_is_screened_through_the_file_form_of_the_check() -> None:
    safety = FakeSafety()
    a, b = source(), dest(safety=safety)
    pdf = b"%PDF-1.7 fake bytes"
    stored = a.render(pdf, "application/pdf")
    record, content = carried(a, stored)
    got = b.store.import_version(b.scope, record, content)
    assert safety.calls == [{"text": "", "content": pdf, "mime_type": "application/pdf"}]
    assert got.record["screening"] == "clean" and got.record["redacted"] is False


# --- AR-04 caps, before hashing ------------------------------------------------------------------------------------


def test_FR_MEM_10_caps_are_checked_before_anything_is_hashed() -> None:
    a, b = source(), dest()
    _stored, record, _content = put_v1(a)
    too_long_text = b"x" * (2 * MB + 1)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, forge(record, too_long_text), too_long_text)
    big_file = Sized(50 * MB + 1)
    pdf = dict(
        record,
        media_type="application/pdf",
        origin={"kind": "upload", "unit": None, "agent": None},
        idempotency_key=None,
    )
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, forge(pdf, big_file), big_file)
    assert b.hasher.calls == 0 and empty(b)


def test_FR_MEM_10_the_world_total_of_200_000_000_bytes_holds_after_an_import() -> None:
    blobs = SizeOnlyBlobs()
    a, b = source(), make_rig("custom", None, blobs=blobs, scope=DEST)
    for _ in range(3):
        b.upload(Sized(50 * MB, b"y"), "application/pdf")  # 150 MB held in the importer's world
    stored = a.upload(Sized(50 * MB, b"x"), "application/pdf")
    record, content = dict(stored.record, sources=[]), Sized(50 * MB, b"x")
    got = b.store.import_version(b.scope, record, content)  # exactly 200,000,000
    assert got.version == 1
    tiny = a.put(b"one more byte\n")
    r2, c2 = carried(a, tiny)
    with pytest.raises(ArtifactRefused):
        b.store.import_version(b.scope, r2, c2)
    assert b.store.head(b.scope, tiny.ref) is None


# --- atomic ----------------------------------------------------------------------------------------------------------


class FailingBlobs(MemoryBlobBackend):
    def create(self, key: str, data: bytes) -> None:
        raise OSError("the blob backend is down")


def test_FR_MEM_10_a_backend_failure_stores_nothing_and_uses_no_version_number() -> None:
    a = source()
    b = make_rig("custom", None, blobs=FailingBlobs(), scope=DEST)
    stored, record, content = put_v1(a)
    with pytest.raises(OSError):
        b.store.import_version(b.scope, record, content)
    assert b.meta.inner.paths() == [] and b.store.head(b.scope, stored.ref) is None
    healthy = dest()
    assert healthy.store.import_version(healthy.scope, record, content).ref == stored.ref


# --- property: any sequence of versions copies over exactly ----------------------------------------------------------

TEXT = st.text(alphabet=string.ascii_letters + string.digits + " \n.,", min_size=1, max_size=60).filter(
    lambda t: t.strip()
)
KINDS = st.sampled_from(["text/markdown", "text/csv", "application/json"])
OPS = st.lists(st.tuples(KINDS, st.integers(0, 50), TEXT, st.booleans()), min_size=1, max_size=15)


def _body(media: str, text: str) -> bytes:
    return {"text/markdown": text, "text/csv": "a,b\n" + text, "application/json": json.dumps({"t": text})}[
        media
    ].encode()


@given(ops=OPS)
def test_FR_MEM_10_property_every_version_copies_over_with_the_same_bytes_hash_and_refs(ops) -> None:
    a, b = source(), dest()
    stored = []
    ids: list[str] = []
    for media, pick, text, extend in ops:
        parent = None
        if extend and ids:
            artifact_id = ids[pick % len(ids)]
            parent = {"artifact_id": artifact_id, "version": pick % len(a.store.versions(a.scope, artifact_id)) + 1}
            if a.store.head(a.scope, parent).record["media_type"] != media:
                parent = None
        version = a.put(_body(media, text), media_type=media, parent=parent)
        if version.version == 1:
            ids.append(version.artifact_id)
        stored.append(version)
    for version in stored:  # ascending per artifact: put order is a valid import order
        b.store.import_version(b.scope, *carried(a, version))
    for version in stored:
        got = b.store.head(b.scope, version.ref)
        assert got is not None and got.record["content_sha256"] == version.record["content_sha256"]
        assert b.store.read(b.scope, version.ref) == a.store.read(a.scope, version.ref)
        assert (
            got.record["parents"] == version.record["parents"]
            and got.record["created_at"] == version.record["created_at"]
        )
    for artifact_id in ids:
        assert [v.ref for v in b.store.versions(b.scope, artifact_id)] == [
            v.ref for v in a.store.versions(a.scope, artifact_id)
        ]
    snapshot = (b.meta.inner.paths(), b.blobs.inner.keys())
    for version in stored:  # importing everything again changes nothing
        b.store.import_version(b.scope, *carried(a, version))
    assert (b.meta.inner.paths(), b.blobs.inner.keys()) == snapshot
