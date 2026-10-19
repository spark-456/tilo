"""FR-MEM-10 tamper detection (PRD 13.2 "SHA-256 per record plus a per-run hash chain; any edit breaks the chain", 13.2
artifact versions "Content hashes", 13.4 bundles are for incident review, so they must show tampering): a bundle that
was altered after export is refused as a whole and nothing is imported (no event, view, artifact record, blob or
archive line written). Refused means `BundleRefused` (a ValueError), never another exception.

Two kinds of forgery: an edit that leaves the bundle's SHA-256 index stale (caught by the index), and an edit by someone
who also recomputed the index (caught by the cross-checks: the archive hash chain and head, the artifact hashes the
events and records carry, `seq` order, the counts, and the closed set of entries). A forger who edits an event AND the
index leaves no trace inside the bundle, so `import_run(expected_sha256=)` takes the bundle's digest from a trusted
side channel; it is tested below. See API_FR_MEM_10.md. Fails now: `ModuleNotFoundError: tilo_harness.run_bundle`.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from bundle_support import (
    ARCHIVE,
    BUNDLE_JSON,
    EVENTS,
    assert_nothing_imported,
    assert_replayed_identically,
    build_source_run,
    do_export,
    do_import,
    edited,
    jb,
    jsonl,
    lines_of,
    make_dest,
    meta_of,
    names,
    refused_and_nothing_written,
    refused_type,
    sha,
    unpack,
)
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.usefixtures("block_network")


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


def _brief_v1(src) -> str:
    return f"artifacts/{src.art_ids['brief']}/v000001"


def _set_line(entries, name, index, change):
    lines = [json.loads(x) for x in lines_of(entries[name])]
    lines[index] = change(lines[index])
    entries[name] = jsonl(lines)


def _forged_content_and_record(src):
    """Version 1 of the brief with other bytes AND a record that agrees with them: only the `artifact.created` event
    and the manifest still carry the real hash."""

    def edit(entries):
        base = _brief_v1(src)
        other = entries[f"{base}/content"] + b"Forged line.\n"
        entries[f"{base}/content"] = other
        record = json.loads(entries[f"{base}/record.json"])
        record["content_sha256"], record["size_bytes"] = sha(other), len(other)
        entries[f"{base}/record.json"] = jb(record)

    return edit


# name -> (edit, recompute the index, recompute the counts). Each is built from a good bundle's entries.
def _cases(src):
    base = _brief_v1(src)

    def drop_event(entries):
        lines = lines_of(entries[EVENTS])
        del lines[5]
        entries[EVENTS] = ("\n".join(lines) + "\n").encode()

    def swap_events(entries):
        lines = lines_of(entries[EVENTS])
        lines[6], lines[7] = lines[7], lines[6]
        entries[EVENTS] = ("\n".join(lines) + "\n").encode()

    def cut_events_tail(entries):
        lines = lines_of(entries[EVENTS])
        entries[EVENTS] = ("\n".join(lines[:-1]) + "\n").encode()

    def archive_payload(entries):
        _set_line(entries, ARCHIVE, 1, lambda r: r | {"payload": {"tool": "fetch", "content": "Firm Faa lost money."}})

    def archive_swap(entries):
        lines = lines_of(entries[ARCHIVE])
        lines[0], lines[1] = lines[1], lines[0]
        entries[ARCHIVE] = ("\n".join(lines) + "\n").encode()

    def archive_cut(entries):
        entries[ARCHIVE] = ("\n".join(lines_of(entries[ARCHIVE])[:-1]) + "\n").encode()

    def archive_drop_middle(entries):
        lines = lines_of(entries[ARCHIVE])
        del lines[1]
        entries[ARCHIVE] = ("\n".join(lines) + "\n").encode()

    def versions_removed(entries):
        for name in [n for n in entries if n.startswith(f"artifacts/{src.art_ids['table']}/")]:
            del entries[name]

    def smuggled_version(entries):
        stray = f"artifacts/{src.art_ids['brief']}/v000004"
        for suffix in ("record.json", "content", "manifests.json"):
            entries[f"{stray}/{suffix}"] = entries[f"artifacts/{src.art_ids['brief']}/v000003/{suffix}"]
        record = json.loads(entries[f"{stray}/record.json"])
        record["artifact"] = {"artifact_id": src.art_ids["brief"], "version": 4}
        record["parents"] = [{"artifact_id": src.art_ids["brief"], "version": 3}]
        entries[f"{stray}/record.json"] = jb(record)

    def record_names_other_artifact(entries):
        record = json.loads(entries[f"{base}/record.json"])
        record["artifact"] = {"artifact_id": src.art_ids["prices"], "version": 1}
        entries[f"{base}/record.json"] = jb(record)

    def swap_blobs(entries):
        a = f"artifacts/{src.art_ids['prices']}/v000001/content"
        entries[f"{base}/content"], entries[a] = entries[a], entries[f"{base}/content"]

    def manifest_hash(entries):
        revisions = json.loads(entries[f"{base}/manifests.json"])
        revisions[0]["manifest"]["content_sha256"] = "0" * 64
        entries[f"{base}/manifests.json"] = jb(revisions)

    def manifest_gap(entries):
        revisions = json.loads(entries[f"artifacts/{src.art_ids['brief']}/v000002/manifests.json"])
        revisions[0]["n"] = 2
        entries[f"artifacts/{src.art_ids['brief']}/v000002/manifests.json"] = jb(revisions)

    def index_hash_wrong(entries):
        meta = meta_of(entries)
        meta["entries"][EVENTS] = "0" * 64
        entries[BUNDLE_JSON] = jb(meta)

    def head_forged(entries):  # the archive tail is cut and everything is consistent but the head in bundle.json
        archive_cut(entries)

    return {
        # a stale index: any edit to an entry is a hash mismatch
        "event_summary_altered": (
            lambda e: _set_line(e, EVENTS, 3, lambda x: x | {"summary": "Altered."}),
            False,
            False,
        ),
        "artifact_bytes_altered": (
            lambda e: e.__setitem__(f"{base}/content", e[f"{base}/content"] + b"!"),
            False,
            False,
        ),
        "record_altered": (
            lambda e: e.__setitem__(
                f"{base}/record.json", e[f"{base}/record.json"].replace(b"text/markdown", b"text/csv")
            ),
            False,
            False,
        ),
        "manifest_altered": (manifest_hash, False, False),
        "archive_record_altered": (archive_payload, False, False),
        "blob_missing": (lambda e: e.pop(f"{base}/content"), False, False),
        "events_entry_missing": (lambda e: e.pop(EVENTS), False, False),
        "unlisted_extra_entry": (lambda e: e.__setitem__("notes.txt", b"hello"), False, False),
        "index_names_a_wrong_hash": (index_hash_wrong, False, False),
        # a recomputed index: the cross-checks still refuse
        "bytes_altered_index_recomputed": (
            lambda e: e.__setitem__(f"{base}/content", e[f"{base}/content"] + b"!"),
            True,
            True,
        ),
        "bytes_and_record_forged_index_recomputed": (_forged_content_and_record(src), True, True),
        "blob_missing_index_recomputed": (lambda e: e.pop(f"{base}/content"), True, True),
        "blobs_swapped_index_recomputed": (swap_blobs, True, True),
        "manifest_hash_forged_index_recomputed": (manifest_hash, True, True),
        "manifest_revision_gap_index_recomputed": (manifest_gap, True, True),
        "event_missing_mid_stream": (drop_event, True, True),
        "events_reordered": (swap_events, True, True),
        "events_tail_cut_count_stale": (cut_events_tail, True, False),
        "archive_record_altered_index_recomputed": (archive_payload, True, True),
        "archive_records_reordered": (archive_swap, True, True),
        "archive_record_missing_mid_chain": (archive_drop_middle, True, True),
        "archive_tail_cut_head_stale": (head_forged, True, True),
        "version_entries_removed_but_events_name_them": (versions_removed, True, True),
        "version_smuggled_in_that_no_event_recorded": (smuggled_version, True, True),
        "record_names_another_artifact_than_its_path": (record_names_other_artifact, True, True),
    }


CASE_NAMES = sorted(
    [
        "event_summary_altered",
        "artifact_bytes_altered",
        "record_altered",
        "manifest_altered",
        "archive_record_altered",
        "blob_missing",
        "events_entry_missing",
        "unlisted_extra_entry",
        "index_names_a_wrong_hash",
        "bytes_altered_index_recomputed",
        "bytes_and_record_forged_index_recomputed",
        "blob_missing_index_recomputed",
        "blobs_swapped_index_recomputed",
        "manifest_hash_forged_index_recomputed",
        "manifest_revision_gap_index_recomputed",
        "event_missing_mid_stream",
        "events_reordered",
        "events_tail_cut_count_stale",
        "archive_record_altered_index_recomputed",
        "archive_records_reordered",
        "archive_record_missing_mid_chain",
        "archive_tail_cut_head_stale",
        "version_entries_removed_but_events_name_them",
        "version_smuggled_in_that_no_event_recorded",
        "record_names_another_artifact_than_its_path",
    ]
)


def test_FR_MEM_10_every_tamper_case_is_listed(src) -> None:
    assert sorted(_cases(src)) == CASE_NAMES


@pytest.mark.parametrize("case", CASE_NAMES)
def test_FR_MEM_10_a_tampered_bundle_is_refused_and_nothing_is_imported(src, tmp_path, case) -> None:
    edit, index, count = _cases(src)[case]
    tampered = edited(do_export(src), edit, index=index, count=count)
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, tampered)
    assert_nothing_imported(dest)


def test_FR_MEM_10_the_untouched_bundle_still_imports_after_every_refusal(src, tmp_path) -> None:
    """A refusal leaves the importer's world usable: the good bundle then imports into the very same world."""
    good = do_export(src)
    dest = make_dest(tmp_path, src.layout)
    for case in ("event_missing_mid_stream", "archive_tail_cut_head_stale", "blobs_swapped_index_recomputed"):
        edit, index, count = _cases(src)[case]
        refused_and_nothing_written(dest, edited(good, edit, index=index, count=count))
    do_import(dest, good)
    assert_replayed_identically(src, dest)


# --- the trusted digest ---------------------------------------------------------------------------------------------


def test_FR_MEM_10_a_matching_expected_digest_is_accepted(src, tmp_path) -> None:
    bundle = do_export(src)
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, bundle, expected_sha256=sha(bundle))
    assert_replayed_identically(src, dest)


def test_FR_MEM_10_another_digest_refuses_the_bundle_even_if_it_is_internally_consistent(src, tmp_path) -> None:
    """The forger who edits an event and recomputes the index leaves no trace inside the bundle; the digest from the
    trusted side channel is what catches it."""
    bundle = do_export(src)
    forged = edited(
        bundle, lambda e: _set_line(e, EVENTS, 3, lambda x: x | {"summary": "Altered."}), index=True, count=True
    )
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, forged, expected_sha256=sha(bundle))
    refused_and_nothing_written(dest, bundle, expected_sha256="0" * 64)
    refused_and_nothing_written(dest, bundle, expected_sha256=sha(bundle).upper())
    assert_nothing_imported(dest)


# --- properties ------------------------------------------------------------------------------------------------------

NO_SHRINK = (Phase.explicit, Phase.reuse, Phase.generate)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture], phases=NO_SHRINK)
@given(entry=st.integers(0, 10_000), position=st.integers(0, 10_000_000), mask=st.integers(1, 255))
def test_FR_MEM_10_property_flipping_any_byte_of_any_entry_is_refused_and_imports_nothing(
    src, entry, position, mask
) -> None:
    entries = unpack(do_export(src))
    candidates = sorted(n for n in entries if n != BUNDLE_JSON)
    name = candidates[entry % len(candidates)]
    data = bytearray(entries[name])
    if not data:
        return
    data[position % len(data)] ^= mask
    entries[name] = bytes(data)
    from bundle_support import pack

    with tempfile.TemporaryDirectory() as tmp:
        dest = make_dest(Path(tmp), src.layout)
        refused_and_nothing_written(dest, pack(entries))
        assert_nothing_imported(dest)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture], phases=NO_SHRINK)
@given(position=st.integers(0, 10_000_000), mask=st.integers(1, 255))
def test_FR_MEM_10_property_a_flipped_byte_anywhere_in_the_file_is_refused_cleanly_or_changes_nothing(
    src, position, mask
) -> None:
    """Zip headers and compressed streams too: the importer raises only BundleRefused (never BadZipFile, KeyError,
    UnicodeDecodeError, ...). A flip in an ignored header field may still import, and then the replay is identical."""
    good = do_export(src)
    raw = bytearray(good)
    raw[position % len(raw)] ^= mask
    with tempfile.TemporaryDirectory() as tmp:
        dest = make_dest(Path(tmp), src.layout)
        before = dest.snapshot()
        try:
            do_import(dest, bytes(raw))
        except refused_type():
            assert dest.snapshot() == before
        else:
            assert_replayed_identically(src, dest)


def test_FR_MEM_10_the_index_lists_every_entry_so_no_entry_can_be_added_or_dropped_unseen(src) -> None:
    entries = unpack(do_export(src))
    assert set(meta_of(entries)["entries"]) == set(entries) - {BUNDLE_JSON}
    assert (
        len(names(entries, "/record.json")) == len(names(entries, "/content")) == len(names(entries, "/manifests.json"))
    )
