"""PROD-WIRE 2b (issue #522): `GcsArchiveStore(bucket)` is a `tilo_archive.archive.Store` (FR-MEM-04, PRD 13.2) on
the CMEK `archive` bucket. GCS objects are immutable, so one object holds one line.

Pinned: line number `n` (1 first, highest existing + 1, a gap is never filled) goes to the object
`{org_id}/{run_id}/{n:08d}.jsonl` holding `line + "\\n"` in UTF-8; every upload is create-only
(`if_generation_match=0`) and an index taken by another writer is retried with the next one; `read_lines` lists
`{org_id}/{run_id}/` (the trailing slash: `r_1` must not read `r_10`) and returns the lines in index order. Ids that
`RunArchive` would refuse are a `ValueError` here too. The real-GCS check is the deployed smoke (PR4).
`tilo_api.run_stores` does not exist yet: every test here fails at collection with `ModuleNotFoundError`.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import pytest
from _prod_wire_2b_lib import ORG, RUN, SECRET, FakeBucket, mask
from tilo_api.run_stores import GcsArchiveStore
from tilo_archive import RunArchive, verify_chain


def obj(n: int, org: str = ORG, run: str = RUN) -> str:
    return f"{org}/{run}/{n:08d}.jsonl"


def archive(bucket: FakeBucket, run: str = RUN) -> RunArchive:
    return RunArchive(GcsArchiveStore(bucket), org_id=ORG, run_id=run, redactor=lambda p: p,
                      clock=lambda: datetime(2026, 10, 7, tzinfo=UTC))  # fmt: skip


def test_PROD_WIRE_2b_archive_one_create_only_object_per_line_named_by_index():
    bucket = FakeBucket(versioned=False)
    store = GcsArchiveStore(bucket)
    lines = [f'{{"n":{i}}}' for i in range(1, 13)]
    for line in lines:
        store.append_line(ORG, RUN, line)
    assert bucket.live_names() == [obj(i) for i in range(1, 13)]
    assert bucket.live_bytes(obj(3)) == b'{"n":3}\n'
    assert store.read_lines(ORG, RUN) == lines  # index order, not the order of the strings "10" and "2"
    assert store.read_lines(ORG, "r_unknown") == [] and store.read_lines("org_unknown", RUN) == []
    assert {match for _, match in bucket.upload_log} == {0}


def test_PROD_WIRE_2b_archive_the_next_index_is_the_highest_plus_one_and_nothing_is_overwritten():
    bucket = FakeBucket(versioned=False)
    bucket.plant(obj(1), b'{"seed":1}\n')
    bucket.plant(obj(3), b'{"seed":3}\n')
    store = GcsArchiveStore(bucket)
    store.append_line(ORG, RUN, '{"new":1}')
    assert bucket.live_names() == [obj(1), obj(3), obj(4)] and bucket.live_bytes(obj(3)) == b'{"seed":3}\n'
    assert store.read_lines(ORG, RUN) == ['{"seed":1}', '{"seed":3}', '{"new":1}']


def test_PROD_WIRE_2b_archive_a_run_reads_only_its_own_lines():
    bucket = FakeBucket(versioned=False)
    store = GcsArchiveStore(bucket)
    for org, run in [(ORG, "r_1"), (ORG, "r_10"), (ORG + "x", "r_1")]:
        store.append_line(org, run, f'{{"of":"{org}/{run}"}}')
    assert store.read_lines(ORG, "r_1") == [f'{{"of":"{ORG}/r_1"}}'] and len(store.read_lines(ORG, "r_10")) == 1
    assert store.read_lines(ORG + "x", "r_1") == [f'{{"of":"{ORG}x/r_1"}}']


def test_PROD_WIRE_2b_archive_a_run_archive_over_it_verifies_its_chain_across_a_reopen():
    bucket = FakeBucket(versioned=False)
    first = RunArchive(
        GcsArchiveStore(bucket), org_id=ORG, run_id=RUN, redactor=lambda p: {**p, "text": mask(p["text"])}
    )
    for text in ["plain", f"leaks {SECRET}", "line separator"]:
        first.append("tool_call", {"text": text})
    assert verify_chain(first.records(), expected_head=first.head()) == []
    reopened = archive(bucket)
    assert reopened.head() == first.head() and reopened.records()[2]["payload"]["text"] == "line separator"
    assert reopened.append("channel_out", {"text": "next"}) == f"{RUN}/4"
    assert verify_chain(archive(bucket).records(), expected_head=reopened.head()) == []
    assert not any(SECRET.encode() in bucket.live_bytes(n) for n in bucket.live_names()), "redacted before it lands"


def test_PROD_WIRE_2b_archive_two_appenders_never_lose_or_overwrite_a_line():
    bucket, errors = FakeBucket(versioned=False), []
    meeting, seen = threading.Barrier(2, timeout=30), set()

    def first_upload_meets_the_other(name: str) -> None:
        if threading.get_ident() not in seen:
            seen.add(threading.get_ident())
            meeting.wait()  # both appenders take index 1 at the same moment

    bucket.before_upload = first_upload_meets_the_other

    def writer(tag: str) -> None:
        try:
            store = GcsArchiveStore(bucket)  # its own instance: another process in effect
            for i in range(20):
                store.append_line(ORG, RUN, f'{{"w":"{tag}","i":{i}}}')
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=writer, args=(tag,)) for tag in "ab"]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    lines = GcsArchiveStore(bucket).read_lines(ORG, RUN)
    assert errors == [] and bucket.live_names() == [obj(i) for i in range(1, 41)]
    assert sorted(lines) == sorted(f'{{"w":"{t}","i":{i}}}' for t in "ab" for i in range(20))
    for tag in "ab":  # each appender's own lines keep their order
        assert [ln for ln in lines if f'"w":"{tag}"' in ln] == [f'{{"w":"{tag}","i":{i}}}' for i in range(20)]
    assert {match for _, match in bucket.upload_log} == {0} and len(bucket.upload_log) > 40, "the lost race was retried"


def test_PROD_WIRE_2b_archive_tampering_with_an_object_fails_verify_chain():
    bucket = FakeBucket(versioned=False)
    run = archive(bucket)
    for i in range(1, 5):
        run.append("model_call", {"i": i})
    head = run.head()
    assert verify_chain(archive(bucket).records(), expected_head=head) == []
    original = bucket.live_bytes(obj(3))
    bucket.tamper(obj(3), original.replace(b'{"i":3}', b'{"i":9}'))
    assert bucket.live_bytes(obj(3)) != original
    assert any("seq 3" in p and "hash mismatch" in p for p in verify_chain(archive(bucket).records()))
    bucket.tamper(obj(3), original)
    bucket.drop(obj(2))
    assert verify_chain(archive(bucket).records()) != [], "a deleted object is a gap in the chain"
    bucket.drop(obj(4))
    assert verify_chain(archive(bucket).records(), expected_head=head) != [], "a cut tail is not the expected head"


@pytest.mark.parametrize("org,run", [("../org_a", "r_1"), ("org_a", "r_1/../r_2"), ("org_a/x", "r_1"), ("", "r_1"),
                                     ("org_a", ""), ("org_a", "r_1\n"), ("org_a", "r 1")])  # fmt: skip
def test_PROD_WIRE_2b_archive_an_unsafe_id_is_refused_and_the_bucket_is_untouched(org, run):
    bucket = FakeBucket()
    store = GcsArchiveStore(bucket)
    for call in (lambda: store.append_line(org, run, "{}"), lambda: store.read_lines(org, run)):
        with pytest.raises(ValueError):
            call()
    assert bucket.upload_log == [] and bucket.live_names() == []
