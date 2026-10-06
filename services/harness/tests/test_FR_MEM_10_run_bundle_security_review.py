"""FR-MEM-10 security review round 1 (PRD 13.2 append-only, hash-chained archive; 13.4 bundles; 16.2 secrets; AR-02,
AR-08): the cases the review's probes found, each pinned here.

- A ZIP whose central directory under-declares an entry's size (a deflate bomb with a CRC of the declared prefix) or
  declares a huge entry count is refused without inflating or listing it.
- A secret under a digest-named key (`fingerprint`, `content_sha256`) is still a secret unless the value is a digest;
  every string of every archive record is scanned, and an archive record must have the raw archive's exact shape.
- An import never appends after a chain it cannot vouch for: another world's live chain of the same org and run is
  left untouched (a partial chain is completed only for a bundle authenticated by `expected_sha256`).
- Two imports of one bundle into one world at once are serialised: one writes, the other finds it all there.
- A world that holds the whole run writes nothing, and refuses when its stores lack part of it.
- A record from after the export, of another run, or a restore that is not an exact copy of its parent is refused.
"""

from __future__ import annotations

import json
import struct
import threading
import time
import tracemalloc
import zlib

import pytest
from bundle_support import (
    ARCHIVE,
    BUNDLE_JSON,
    ORG,
    RUN,
    SECRET,
    assert_nothing_imported,
    assert_replayed_identically,
    build_source_run,
    do_export,
    do_import,
    edited,
    jb,
    lines_of,
    make_dest,
    pack,
    recount,
    refused_and_nothing_written,
    refused_type,
    reindex,
    retarget,
    revisions_of,
    sha,
    unpack,
)

pytestmark = pytest.mark.usefixtures("block_network")

MiB = 2**20


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


# --- ZIP bombs ------------------------------------------------------------------------------------------------------


def _lying_zip(names: list[str], inflated: int, declared: int) -> bytes:
    """Entries whose deflate stream inflates to `inflated` bytes of zeros while the directory declares `declared`
    (with the CRC of the declared prefix)."""
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    stream = b"".join(packer.compress(b"\0" * MiB) for _ in range(inflated // MiB)) + packer.flush()
    crc, body, central = zlib.crc32(b"\0" * declared), bytearray(), bytearray()
    for name in names:
        raw, offset = name.encode(), len(body)
        body += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0x21, crc, len(stream), declared, len(raw), 0)
        body += raw + stream
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII", 0x02014B50, (3 << 8) | 20, 20, 0, 8, 0, 0x21, crc, len(stream), declared,
            len(raw), 0, 0, 0, 0, 0o100644 << 16, offset,
        ) + raw  # fmt: skip
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(names), len(names), len(central), len(body), 0)
    return bytes(body + central + end)


def _peak(fn) -> int:
    tracemalloc.start()
    try:
        fn()
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_FR_MEM_10_an_entry_that_inflates_past_its_declared_size_is_refused_without_inflating_it(src, tmp_path):
    bundle = _lying_zip(["bundle.json", "events.jsonl", "archive.jsonl"], inflated=32 * MiB, declared=10)
    dest = make_dest(tmp_path, src.layout)

    def run() -> None:
        with pytest.raises(refused_type()):
            do_import(dest, bundle)

    assert _peak(run) < 4 * MiB, "the bomb was inflated in memory"
    assert_nothing_imported(dest)


def test_FR_MEM_10_a_huge_or_understated_entry_count_is_refused_before_the_directory_is_listed(src, tmp_path):
    name, n = b"a", 200_000
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0x21, 0, 0, 0, len(name), 0) + name
    one = struct.pack(
        "<IHHHHHHIIIHHHHHII", 0x02014B50, (3 << 8) | 20, 20, 0, 0, 0, 0x21, 0, 0, 0, len(name), 0, 0, 0, 0,
        0o100644 << 16, 0,
    ) + name  # fmt: skip
    central = one * n
    zip64 = struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, n, n, len(central), len(local))
    locator = struct.pack("<IIQI", 0x07064B50, 0, len(local) + len(central), 1)
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    many = local + central + zip64 + locator + end
    plain = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 40_000, 40_000, len(one) * 40_000, len(local), 0)
    over = local + one * 40_000 + plain  # no ZIP64, a count over max_entries
    good = bytearray(do_export(src))
    good[-14:-10] = struct.pack("<HH", 1, 1)  # the end record understates the entry count
    dest = make_dest(tmp_path, src.layout)
    for bundle in (many, over, bytes(good)):
        started = time.perf_counter()
        assert _peak(lambda b=bundle: refused_and_nothing_written(dest, b)) < 8 * MiB
        assert time.perf_counter() - started < 5
    assert_nothing_imported(dest)


def _overlapping_zip(n: int, region: int) -> bytes:
    """Fifield-style overlap (review round 2): each entry's deflate stream stores the next local header, then runs
    into one shared region of empty stored blocks. Every declared size and CRC holds, but inflating every entry
    would scan the shared region n times."""

    def local(name: bytes) -> bytes:
        return struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0x21, 0, 0, 0, len(name), 0) + name

    names = [f"artifacts/art_{i:08d}/v000001/content".encode() for i in range(n)]
    headers = [local(name) for name in names]
    body, offsets, starts = bytearray(), [], []
    for i, header in enumerate(headers):
        offsets.append(len(body))
        body += header
        starts.append(len(body))
        if i + 1 < n:  # a stored block quoting the next local header
            body += b"\x00" + struct.pack("<HH", len(headers[i + 1]), len(headers[i + 1]) ^ 0xFFFF)
    body += b"\x00\x00\x00\xff\xff" * (region // 5) + b"\x01\x00\x00\xff\xff"
    central = bytearray()
    for i, name in enumerate(names):
        out = b"".join(headers[i + 1 :])
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII", 0x02014B50, (3 << 8) | 20, 20, 0, 8, 0, 0x21, zlib.crc32(out),
            len(body) - starts[i], len(out), len(name), 0, 0, 0, 0, 0o100644 << 16, offsets[i],
        ) + name  # fmt: skip
    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, n, n, len(central), len(body), 0)
    return bytes(body + central + end)


def test_FR_MEM_10_overlapping_entries_are_refused_before_anything_is_inflated(src, tmp_path) -> None:
    bundle = _overlapping_zip(200, 8 * MiB)  # inflating each entry would scan about 1.6 GB in all
    dest = make_dest(tmp_path, src.layout)
    started = time.perf_counter()
    error = refused_and_nothing_written(dest, bundle)
    assert time.perf_counter() - started < 1, "refused before any entry was inflated"
    assert "overlap" in str(error)


def test_FR_MEM_10_the_import_locks_go_away_once_no_import_holds_them(src, tmp_path) -> None:
    import gc

    from tilo_harness import run_bundle

    do_import(make_dest(tmp_path, src.layout), do_export(src))
    gc.collect()
    assert len(run_bundle._LOCKS) == 0, "one lock per world and per run is not kept forever"


# --- secrets in the archive -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["fingerprint", "content_sha256", "hash"])
def test_FR_MEM_10_export_scans_a_digest_named_key_whose_value_is_not_a_digest(tmp_path, key) -> None:
    run = build_source_run(tmp_path / "run")
    run.rig.archive.append("tool_call", {"tool": "fetch", key: SECRET})
    with pytest.raises(refused_type()) as caught:
        do_export(run)
    assert SECRET not in str(caught.value)


def _chained(bundle: bytes, extras: list[dict]) -> bytes:
    """A forger's bundle: the same entries plus archive records chained on, head, counts and index recomputed."""
    from tilo_archive.record import canonical_json, record_hash

    entries = unpack(bundle)
    records = [json.loads(line) for line in lines_of(entries[ARCHIVE])]
    for extra in extras:
        prev = records[-1]
        record = {"v": "1.0", "run_id": prev["run_id"], "seq": prev["seq"] + 1, "kind": "tool_call", "ts": prev["ts"]}
        record |= {"payload": {"tool": "fetch", "content": "forged"}, "prev_hash": prev["hash"]} | extra
        record["hash"] = record_hash(record)
        records.append(record)
    entries[ARCHIVE] = "".join(canonical_json(r) + "\n" for r in records).encode("utf-8")
    meta = json.loads(entries[BUNDLE_JSON])
    meta["archive_head"] = {"seq": records[-1]["seq"], "hash": records[-1]["hash"]}
    entries[BUNDLE_JSON] = jb(meta)
    return pack(reindex(recount(entries)))


FORGED_RECORDS = {
    "secret_under_fingerprint": {"payload": {"tool": "fetch", "fingerprint": SECRET}},
    "secret_under_content_sha256": {"payload": {"tool": "fetch", "content_sha256": SECRET}},
    "an_extra_key": {"note": "hello"},
    "an_unknown_kind": {"kind": "teleport"},
    "a_time_that_is_not_a_timestamp": {"ts": "yesterday"},
}


@pytest.mark.parametrize("case", sorted(FORGED_RECORDS))
def test_FR_MEM_10_every_string_and_the_shape_of_every_archive_record_are_checked_on_import(src, tmp_path, case):
    dest = make_dest(tmp_path, src.layout)
    error = refused_and_nothing_written(dest, _chained(do_export(src), [FORGED_RECORDS[case]]))
    assert SECRET not in str(error)
    assert_nothing_imported(dest)


# --- the raw archive of another world -------------------------------------------------------------------------------


def test_FR_MEM_10_an_import_never_appends_to_another_world_s_live_chain_of_the_same_run(tmp_path) -> None:
    from tilo_archive import LocalDirStore

    live = build_source_run(tmp_path / "live")  # world A, still running in org ORG
    chain = live.archive_dir / ORG / f"{RUN}.jsonl"
    before = chain.read_bytes()
    shared = {"org": ORG, "archive_wrapper": lambda _inner: LocalDirStore(live.archive_dir)}
    forged = _chained(do_export(live), [{"payload": {"tool": "fetch", "content": "planted"}}])
    world_b = make_dest(tmp_path, live.layout, world="w_world_b", **shared)
    refused_and_nothing_written(world_b, forged)
    assert chain.read_bytes() == before, "world A's chain is untouched"
    refused_and_nothing_written(world_b, forged, expected_sha256="0" * 64)
    genuine = make_dest(tmp_path, live.layout, world="w_world_c", name="c", **shared)
    do_import(genuine, do_export(live))  # the identical whole chain is shared, never written again
    assert chain.read_bytes() == before
    live.rig.archive.append("tool_call", {"tool": "fetch", "content": "world A keeps working"})
    from tilo_archive.archive import verify_chain

    assert verify_chain([json.loads(x) for x in lines_of(chain.read_bytes())]) == []


# --- concurrency ----------------------------------------------------------------------------------------------------


class SlowArchive:
    """An archive store whose reads are slow, so two imports would interleave without a lock."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def read_lines(self, org_id, run_id):
        time.sleep(0.3)
        return self.inner.read_lines(org_id, run_id)

    def append_line(self, org_id, run_id, line) -> None:
        self.inner.append_line(org_id, run_id, line)


def test_FR_MEM_10_two_imports_of_one_bundle_into_one_world_at_once_write_it_once(src, tmp_path) -> None:
    from tilo_archive.archive import verify_chain

    bundle = do_export(src)
    dest = make_dest(tmp_path, src.layout, archive_wrapper=SlowArchive)
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(do_import(dest, bundle))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(120)
    assert sorted(r.already_imported for r in results) == [False, True]
    assert dest.archive_lines() == src.archive_lines()
    assert verify_chain([json.loads(x) for x in dest.archive_lines()]) == []
    for ref in src.refs():
        assert revisions_of(dest.artifacts, dest.scope, ref) == revisions_of(src.rig.store, src.scope, ref)
    assert dest.stream() == [retarget(e, dest.world) for e in src.events]


def test_FR_MEM_10_a_world_that_holds_the_run_but_lacks_a_manifest_revision_is_refused(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    (revision,) = [p for p in dest.meta.inner.paths() if "/manifests/" in p][:1]
    dest.meta.inner.delete(revision)
    refused_and_nothing_written(dest, do_export(src))


# --- records ----------------------------------------------------------------------------------------------------------


def _edit_record(src, version: int, change):
    name = f"artifacts/{src.art_ids['brief']}/v{version:06d}"

    def edit(entries):
        record = json.loads(entries[f"{name}/record.json"])
        change(record, entries, name)
        entries[f"{name}/record.json"] = jb(record)

    return edit


def _future(record, _entries, _name):
    record["created_at"] = "9999-12-31T23:59:59.999Z"


def _after_export(record, _entries, _name):
    record["created_at"] = "2026-10-08T00:00:00.000Z"  # the bundle was exported on 2026-10-07


def _other_run(record, _entries, _name):
    record["run_id"] = "r_other_run"


def _restore_of_other_bytes(record, entries, name):
    other = entries[f"{name}/content"] + b"Not what version 1 says.\n"
    entries[f"{name}/content"] = other
    record["content_sha256"], record["size_bytes"] = sha(other), len(other)


@pytest.mark.parametrize(
    ("version", "change"),
    [(1, _future), (1, _after_export), (2, _other_run), (3, _restore_of_other_bytes)],
    ids=["created_in_year_9999", "created_after_the_export", "record_of_another_run", "restore_not_an_exact_copy"],
)
def test_FR_MEM_10_a_record_the_run_could_not_have_written_is_refused(src, tmp_path, version, change) -> None:
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, edited(do_export(src), _edit_record(src, version, change), index=True))
    assert_nothing_imported(dest)


def test_FR_MEM_10_the_untouched_bundle_still_replays_after_the_review_checks(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    assert do_import(dest, do_export(src)).verified is False, "without the digest an import is unverified"
    assert_replayed_identically(src, dest)


def test_FR_MEM_10_an_import_is_verified_only_with_a_matching_expected_digest(src, tmp_path) -> None:
    """BQ-MEM10-3: `verified` is true only when `expected_sha256` was given and matched."""
    bundle = do_export(src)
    dest = make_dest(tmp_path, src.layout)
    assert do_import(dest, bundle, expected_sha256=sha(bundle)).verified is True
    assert do_import(dest, bundle).verified is False, "a re-import without the digest is not verified"
