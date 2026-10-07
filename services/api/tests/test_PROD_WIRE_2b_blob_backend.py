"""PROD-WIRE 2b (issue #522): `GcsBlobBackend(bucket)` is a `BlobBackend` (ADR-0018 T8) with the behaviour of
`MemoryBlobBackend`, plus what only GCS needs: create-only through the precondition `if_generation_match=0`, and a
delete that removes every generation (the `artifacts` bucket is versioned). The contract runs over both backends; the
GCS side runs against `FakeBucket` (`_prod_wire_2b_lib`). There is no official GCS emulator: the real-GCS check is the
deployed smoke (PR4). The object name is the store's blob key, unchanged. `tilo_api.run_stores` does not exist yet:
every test here fails at collection with `ModuleNotFoundError`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from _prod_wire_2b_lib import FakeBucket, race
from tilo_api.run_stores import GcsBlobBackend
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend, NewVersion, Origin, Scope

KEY = "orgs/org_a/worlds/w_1/artifacts/art_1/v000001"
OTHER = "orgs/org_a/worlds/w_1/artifacts/art_1/v000002"


@pytest.fixture(params=["memory", "gcs"])
def blobs(request):
    return MemoryBlobBackend() if request.param == "memory" else GcsBlobBackend(FakeBucket())


def test_PROD_WIRE_2b_blob_read_returns_the_exact_bytes_and_a_missing_key_is_file_not_found(blobs):
    data = bytes(range(256)) * 40
    with pytest.raises(FileNotFoundError):
        blobs.read(KEY)
    blobs.create(KEY, data)
    got = blobs.read(KEY)
    assert got == data and type(got) is bytes


def test_PROD_WIRE_2b_blob_create_never_overwrites(blobs):
    blobs.create(KEY, b"first")
    with pytest.raises(FileExistsError):
        blobs.create(KEY, b"second")
    assert blobs.read(KEY) == b"first"
    outcomes = race(lambda i: blobs.create(OTHER, f"writer {i}".encode()))
    assert sorted(outcomes) == ["exists"] * 7 + ["ok"], outcomes


def test_PROD_WIRE_2b_blob_delete_is_idempotent_exact_and_frees_the_key(blobs):
    longer = KEY + "0"  # a key that merely starts with KEY is another blob
    blobs.delete(KEY)
    blobs.create(KEY, b"a")
    blobs.create(longer, b"b")
    blobs.delete(KEY)
    blobs.delete(KEY)
    with pytest.raises(FileNotFoundError):
        blobs.read(KEY)
    assert blobs.read(longer) == b"b"
    blobs.create(KEY, b"again")
    assert blobs.read(KEY) == b"again"


def test_PROD_WIRE_2b_blob_keys_lists_by_prefix_sorted(blobs):
    names = [
        OTHER,
        KEY,
        "orgs/org_a/worlds/w_2/artifacts/art_9/v000001",
        "orgs/org_b/worlds/w_1/artifacts/art_1/v000001",
    ]
    for name in names:
        blobs.create(name, b"x")
    assert blobs.keys("orgs/org_a/worlds/w_1/") == [KEY, OTHER]
    assert blobs.keys("orgs/org_c/") == [] and blobs.keys("orgs/org_a/worlds/w_1/artifacts/art_1/v00000") == [
        KEY,
        OTHER,
    ]
    assert blobs.keys() == sorted(names) == blobs.keys("")


def test_PROD_WIRE_2b_gcs_every_upload_is_create_only_with_if_generation_match_zero():
    bucket = FakeBucket()
    blobs = GcsBlobBackend(bucket)
    blobs.create(KEY, b"a")
    with pytest.raises(FileExistsError):
        blobs.create(KEY, b"b")
    assert bucket.upload_log == [(KEY, 0), (KEY, 0)] and bucket.live_names() == [KEY]  # the name is the key


def test_PROD_WIRE_2b_gcs_delete_removes_every_generation_of_the_key_and_no_other():
    bucket = FakeBucket(versioned=True)
    blobs = GcsBlobBackend(bucket)
    blobs.create(KEY, b"one")
    bucket.blob(KEY).delete()  # in a versioned bucket the live object becomes a noncurrent generation
    assert bucket.live_names() == [] and len(bucket.generations(KEY)) == 1
    blobs.create(KEY, b"two")  # the precondition holds: there is no live generation
    blobs.create(OTHER, b"keep")
    assert len(bucket.generations(KEY)) == 2
    blobs.delete(KEY)
    assert bucket.generations(KEY) == [] and bucket.live_names() == [OTHER] and len(bucket.generations(OTHER)) == 1
    blobs.delete(KEY)


@pytest.mark.parametrize(
    "key", ["", "/orgs/x", "orgs//x", "orgs/x/", "orgs/../x", "orgs/./x", "orgs/a b/x", "orgs/x\n", "a\\b"]
)
def test_PROD_WIRE_2b_gcs_an_unsafe_key_is_refused_and_the_bucket_is_untouched(key):
    bucket = FakeBucket()
    blobs = GcsBlobBackend(bucket)
    for call in (lambda: blobs.create(key, b"x"), lambda: blobs.read(key), lambda: blobs.delete(key)):
        with pytest.raises(ValueError):
            call()
    assert bucket.upload_log == [] and bucket.live_names() == []


def test_PROD_WIRE_2b_gcs_the_artifact_store_puts_reads_and_erases_through_it():
    """FR-MEM-09: retention's delete removes the bytes in every generation, the record last."""
    bucket = FakeBucket(versioned=True)
    store = ArtifactStore(
        MemoryMetaBackend(),
        GcsBlobBackend(bucket),
        clock=lambda: datetime(2026, 10, 7, tzinfo=UTC),
        redactor=lambda text: text,
        archive_lookup=lambda scope, ref: None,
        alert_sink=lambda alert: None,
    )
    scope = Scope("org_acme", "w_alpha", "u_alice")
    done = store.put(
        scope,
        NewVersion(
            "text/markdown", b"# Brief\n", "r_run1", Origin("unit", "U1", "A_writer"), idempotency_key="r_run1:U1:0:0"
        ),
    )
    assert store.read(scope, done.ref) == b"# Brief\n"
    assert bucket.live_names() == [f"orgs/org_acme/worlds/w_alpha/artifacts/{done.ref['artifact_id']}/v000001"]
    [record] = store.retention().records()
    store.retention().delete(record.record_id)
    assert bucket.list_blobs(versions=True) == [], "no generation of the blob is left, live or noncurrent"
    assert store.head(scope, done.ref) is None
