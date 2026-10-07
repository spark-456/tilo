"""PROD-WIRE 2b (issue #522): `GcsArchiveStore(bucket)` is a `tilo_archive.archive.Store` (FR-MEM-04, PRD 13.2) on
the CMEK `archive` bucket. GCS objects are immutable, so one object holds one line.

Pinned: line number `n` (1 first, highest existing + 1, a gap is never filled) goes to the object
`{org_id}/{run_id}/{n:08d}.jsonl` holding `line + "\\n"` in UTF-8; every upload is create-only
(`if_generation_match=0`). Security round 1: a record line (a JSON object with `seq` or `prev_hash`) goes to the index
of its own `seq`, so a second writer of that seq is refused (`FileExistsError`; the caller reopens), never moved to the
next index with a stale prev_hash; a 412 over identical bytes is our own lost-reply upload (success); only a line with
neither key is retried at the next index. `read_lines` lists
`{org_id}/{run_id}/` (the trailing slash: `r_1` must not read `r_10`) and returns the lines in index order. Ids that
`RunArchive` would refuse are a `ValueError` here too. The real-GCS check is the deployed smoke (PR4).
`tilo_api.run_stores` does not exist yet: every test here fails at collection with `ModuleNotFoundError`.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

import pytest
from _prod_wire_2b_lib import ORG, RUN, SECRET, FakeBucket, mask
from tilo_api.run_stores import GcsArchiveStore
from tilo_archive import RunArchive, verify_chain
from tilo_archive.record import canonical_json


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
    """Restated (security round 1, BQ-PW-2B (4)): a record line is named by its own `seq`, so the loser of a race is
    refused (`FileExistsError`) instead of landing at the next index with a stale prev_hash; it reopens and appends
    again. Nothing is lost or overwritten and the one chain verifies."""
    bucket, errors, refused = FakeBucket(versioned=False), [], []
    meeting, seen = threading.Barrier(2, timeout=30), set()

    def first_upload_meets_the_other(name: str) -> None:
        if threading.get_ident() not in seen:
            seen.add(threading.get_ident())
            meeting.wait()  # both appenders take seq 1 at the same moment

    bucket.before_upload = first_upload_meets_the_other

    def writer(tag: str) -> None:
        try:
            store = GcsArchiveStore(bucket)  # its own instance: another process in effect
            run = RunArchive(store, org_id=ORG, run_id=RUN, redactor=lambda p: p)
            for i in range(20):
                while True:
                    try:
                        run.append("tool_call", {"w": tag, "i": i})
                        break
                    except FileExistsError:
                        refused.append(tag)
                        run = RunArchive(store, org_id=ORG, run_id=RUN, redactor=lambda p: p)  # reopen at the head
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=writer, args=(tag,)) for tag in "ab"]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    records = archive(bucket).records()
    payloads = [r["payload"] for r in records]
    assert errors == [] and refused, "the loser of the race for seq 1 was refused"
    assert bucket.live_names() == [obj(i) for i in range(1, 41)]
    assert sorted((p["w"], p["i"]) for p in payloads) == [(t, i) for t in "ab" for i in range(20)]
    for tag in "ab":  # each appender's own lines keep their order
        assert [p["i"] for p in payloads if p["w"] == tag] == list(range(20))
    assert verify_chain(records) == [], "no record landed with a stale prev_hash"
    assert {match for _, match in bucket.upload_log} == {0} and len(bucket.upload_log) > 40, "the lost race was refused"


def test_PROD_WIRE_2b_archive_a_record_is_named_by_its_seq_and_a_second_writer_of_that_seq_is_refused():
    bucket = FakeBucket(versioned=False)
    archive(bucket).append("tool_call", {"i": 1})
    first, second = archive(bucket), archive(bucket)  # two instances at the same head
    assert first.append("tool_call", {"by": "first"}) == f"{RUN}/2"
    with pytest.raises(FileExistsError):
        second.append("tool_call", {"by": "second"})  # its prev_hash is stale: it must never land at index 3
    assert bucket.live_names() == [obj(1), obj(2)] and verify_chain(archive(bucket).records()) == []
    assert archive(bucket).append("tool_call", {"by": "second"}) == f"{RUN}/3"  # a reopen continues the one chain
    assert verify_chain(archive(bucket).records()) == []
    line = archive(bucket).records()[1]
    store = GcsArchiveStore(bucket)
    store.append_line(ORG, RUN, canonical_json(line))  # the same bytes again: our own line, not a second copy
    assert bucket.live_names() == [obj(1), obj(2), obj(3)]
    with pytest.raises(FileExistsError):
        store.append_line(ORG, RUN, canonical_json({**line, "kind": "channel_out"}))
    assert bucket.live_names() == [obj(1), obj(2), obj(3)]


@pytest.mark.parametrize("seq", [0, -1, True, "3", 1.0, 10**8, None])
def test_PROD_WIRE_2b_archive_a_record_line_without_a_usable_seq_is_refused_and_the_bucket_is_untouched(seq):
    bucket = FakeBucket(versioned=False)
    with pytest.raises(ValueError):
        GcsArchiveStore(bucket).append_line(ORG, RUN, json.dumps({"seq": seq, "prev_hash": "0" * 64}))
    with pytest.raises(ValueError):
        GcsArchiveStore(bucket).append_line(ORG, RUN, json.dumps({"prev_hash": "0" * 64}))
    assert bucket.upload_log == []


def test_PROD_WIRE_2b_archive_a_lost_reply_412_is_our_own_line_not_a_duplicate():
    """google-cloud-storage retries a generation-matched upload: a first attempt that saved the bytes but lost its
    answer comes back as 412. That is our own line: the chain must not get it twice."""
    bucket = FakeBucket(versioned=False)
    bucket.lose_reply = lambda name: True
    run = archive(bucket)
    for i in range(1, 6):
        assert run.append("model_call", {"i": i}) == f"{RUN}/{i}"
    assert bucket.live_names() == [obj(i) for i in range(1, 6)]
    assert verify_chain(archive(bucket).records(), expected_head=run.head()) == []
    store = GcsArchiveStore(bucket)  # a line that carries no seq follows the same rule
    store.append_line("org_other", RUN, '{"n":1}')
    store.append_line("org_other", RUN, '{"n":2}')
    assert store.read_lines("org_other", RUN) == ['{"n":1}', '{"n":2}']


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
