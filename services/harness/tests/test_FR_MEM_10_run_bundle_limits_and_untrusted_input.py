"""FR-MEM-10 untrusted bundle input, caps and versioning (PRD 16.1 "input is data, not instructions", 16.2, NFR on
size and count caps; AR-04 caps; the bundle is read from a person's upload or an incident ticket, so every
byte is untrusted):

- Not a ZIP, truncated, or a ZIP with an unlisted, duplicate, directory, symlink or path-traversing entry (zip-slip:
  `..`, an absolute path, a backslash, a drive letter, a NUL, a leading or trailing space or newline, an empty
  segment): refused with `BundleRefused`, whatever else is in it and even if `bundle.json` lists the hostile name. No
  file is created anywhere (the importer's blob and archive directories are real directories under tmp_path in these
  tests).
- Malformed JSON anywhere (bad UTF-8, wrong top-level type, NaN, a 100,000-deep nesting that would blow the stack) is
  refused as `BundleRefused`, never as RecursionError, JSONDecodeError or KeyError.
- `bundle.json` is `{"format": "tilo.run-bundle", "version": "1.0", ...}`: another format or version is refused; the
  required keys and their shapes are checked.
- Caps (`Limits`): bundle bytes, uncompressed bytes (read in a bounded way: a 64 MB run of zeros that deflates to 64
  KB is refused without inflating it), entries, events, archive records, versions. A bundle exactly at a cap passes,
  one over is refused, by both `import_run` and `export_run`. The PRD names no number for them: the defaults are the
  builder's choice and are listed as a decision in the report; these tests pin only the boundary behaviour and that
  the world cap of 200,000,000 bytes (AR-04) fits. Fails now: `ModuleNotFoundError: No module named
  'tilo_harness.run_bundle'`.

"""

from __future__ import annotations

import dataclasses
import tracemalloc
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
    limits,
    lines_of,
    make_dest,
    meta_of,
    names,
    raw_pack,
    rb,
    recount,
    refused_and_nothing_written,
    refused_type,
    reindex,
    unpack,
)

pytestmark = pytest.mark.usefixtures("block_network")

MB = 1_000_000


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


def _tree(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _local_dest(tmp_path, src, **kw):
    from tilo_memory.artifacts import LocalDirBlobBackend

    return make_dest(tmp_path, src.layout, blobs=LocalDirBlobBackend(tmp_path / "blobs"), **kw)


# --- not a bundle ---------------------------------------------------------------------------------------------------


def _not_zips(good: bytes) -> dict[str, bytes]:
    return {
        "empty": b"",
        "text": b"not a zip",
        "zip_magic_only": b"PK\x03\x04",
        "end_of_central_directory_only": b"PK\x05\x06" + b"\x00" * 18,
        "zeros": b"\x00" * 4096,
        "truncated_tail": good[:-30],
        "truncated_head": good[100:],
        "cut_in_half": good[: len(good) // 2],
        "zip_inside_a_zip": raw_pack([("bundle.zip", good)]),
        "json_instead": jb({"format": "tilo.run-bundle"}),
    }


@pytest.mark.parametrize(
    "kind",
    ["empty", "text", "zip_magic_only", "end_of_central_directory_only", "zeros", "truncated_tail", "truncated_head",
     "cut_in_half", "zip_inside_a_zip", "json_instead"],
)  # fmt: skip
def test_FR_MEM_10_bytes_that_are_not_a_run_bundle_are_refused_cleanly(src, tmp_path, kind) -> None:
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, _not_zips(do_export(src))[kind])
    assert_nothing_imported(dest)


# --- zip-slip, duplicates, links ------------------------------------------------------------------------------------

HOSTILE_NAMES = [
    "../evil.txt",
    "../../evil.txt",
    "/etc/evil.txt",
    "/evil.txt",
    "artifacts/../../evil.txt",
    "artifacts/art_x/v000001/../../../evil.txt",
    "..\\evil.txt",
    "artifacts\\evil.txt",
    "C:/evil.txt",
    "C:\\evil.txt",
    "\\\\server\\share\\evil.txt",
    "artifacts//evil.txt",
    "./events.jsonl",
    "events.jsonl\x00.txt",
    "events.jsonl\n",
    " events.jsonl",
    "events.jsonl ",
    "artifacts/./evil.txt",
    "artifacts/",
    "artifacts/art_bad id/v000001/record.json",
    "artifacts/art_x/v1/record.json",
    "artifacts/art_x/v000000/record.json",
    "artifacts/art_x/v000001/record.json/extra",
    "artifacts/art_x/v000001/other.bin",
    "~/evil.txt",
    "%2e%2e/evil.txt",
]


@pytest.mark.parametrize("hostile", HOSTILE_NAMES, ids=[repr(n) for n in HOSTILE_NAMES])
def test_FR_MEM_10_a_hostile_entry_name_is_refused_even_when_the_index_lists_it(src, tmp_path, hostile) -> None:
    entries = unpack(do_export(src))
    entries[hostile] = b"owned"
    reindex(entries)
    recount(entries)
    bundle = raw_pack(list(entries.items()))
    dest = _local_dest(tmp_path, src)
    before = _tree(tmp_path)
    with pytest.raises(refused_type()):
        do_import(dest, bundle)
    assert _tree(tmp_path) == before, "no file or directory was created anywhere"
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path.parent / "evil.txt").exists()
    assert_nothing_imported(dest)


@pytest.mark.parametrize("entry", [BUNDLE_JSON, EVENTS, ARCHIVE, "record", "content", "manifests"])
def test_FR_MEM_10_a_duplicate_entry_is_refused_even_with_the_same_bytes(src, tmp_path, entry) -> None:
    entries = unpack(do_export(src))
    name = {
        "record": names(entries, "/record.json")[0],
        "content": names(entries, "/content")[0],
        "manifests": names(entries, "/manifests.json")[0],
    }.get(entry, entry)
    items = list(entries.items()) + [(name, entries[name])]
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, raw_pack(items))
    # and with other bytes under the same name, the first or the last copy must never be chosen silently
    altered = list(entries.items()) + [(name, entries[name] + b" ")]
    refused_and_nothing_written(dest, raw_pack(altered))
    assert_nothing_imported(dest)


@pytest.mark.parametrize("mode", [0o120777, 0o020644, 0o060644, 0o010644, 0o140755])
def test_FR_MEM_10_a_link_or_device_entry_is_refused(src, tmp_path, mode) -> None:
    entries = unpack(do_export(src))
    target = names(entries, "/content")[0]
    bundle = raw_pack(list(entries.items()), attrs={target: mode << 16})
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, bundle)
    assert_nothing_imported(dest)


def test_FR_MEM_10_a_directory_entry_is_refused_the_set_of_entries_is_closed(src, tmp_path) -> None:
    entries = unpack(do_export(src))
    entries["artifacts/"] = b""
    bundle = raw_pack(list(entries.items()), attrs={"artifacts/": (0o040755 << 16) | 0x10})
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, bundle)


# --- malformed JSON -------------------------------------------------------------------------------------------------

GENERIC = [
    b"{not json",
    b"\xff\xfe\x00broken",
    b"null",
    b'"text"',
    b"7",
    b'{"a": NaN}',
    b"[" * 100_000,
    b'{"a":' * 50_000,
    b"",
]
MALFORMED = [
    (entry, payload) for entry in ("bundle", "events", "archive", "record", "manifests") for payload in GENERIC
]
MALFORMED += [("bundle", b"[]"), ("record", b"[]"), ("manifests", b"{}"), ("events", b"[1]\n"), ("archive", b"[1]\n")]
MALFORMED += [("events", b"{}\n"), ("archive", b"{}\n"), ("events", b'{"seq": 1}\nnot json\n'), ("record", b"{}")]


def _target(entries, entry: str) -> str:
    return {
        "bundle": BUNDLE_JSON,
        "events": EVENTS,
        "archive": ARCHIVE,
        "record": names(entries, "/record.json")[0],
        "manifests": f"{names(entries, '/record.json')[0].rsplit('/', 1)[0]}/manifests.json",
    }[entry]


@pytest.mark.parametrize(("entry", "payload"), MALFORMED, ids=[f"{e}-{i}" for i, (e, _) in enumerate(MALFORMED)])
def test_FR_MEM_10_malformed_json_is_refused_cleanly_never_as_a_stack_or_decode_error(
    src, tmp_path, entry, payload
) -> None:
    def edit(entries):
        entries[_target(entries, entry)] = payload

    bundle = edited(do_export(src), edit, index=entry != "bundle", count=entry != "bundle")
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, bundle)
    assert_nothing_imported(dest)


# --- bundle.json: format, version, shapes ---------------------------------------------------------------------------


def _set_meta(**changes):
    def edit(entries):
        meta = meta_of(entries)
        for key, value in changes.items():
            if value is KeyError:
                meta.pop(key)
            else:
                meta[key] = value
        entries[BUNDLE_JSON] = jb(meta)

    return edit


@pytest.mark.parametrize("version", ["2.0", "0.9", "1", "3.1", "", "1.0 ", "v1.0", 1.0, 1, None, ["1.0"]])
def test_FR_MEM_10_an_unknown_bundle_version_is_refused(src, tmp_path, version) -> None:
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, edited(do_export(src), _set_meta(version=version)))


@pytest.mark.parametrize("fmt", ["tilo.other", "", "TILO.RUN-BUNDLE", "tilo.run-bundle ", None, 7])
def test_FR_MEM_10_another_format_is_refused(src, tmp_path, fmt) -> None:
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, edited(do_export(src), _set_meta(format=fmt)))


def test_FR_MEM_10_version_1_0_is_the_format_written_and_read(src, tmp_path) -> None:
    entries = unpack(do_export(src))
    assert meta_of(entries)["format"] == "tilo.run-bundle" and meta_of(entries)["version"] == "1.0"
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    assert_replayed_identically(src, dest)


@pytest.mark.parametrize("key", ["format", "version", "run_id", "exported_at", "counts", "archive_head", "entries"])
def test_FR_MEM_10_every_bundle_json_key_is_required(src, tmp_path, key) -> None:
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, edited(do_export(src), _set_meta(**{key: KeyError})))


BAD_META = [
    {"run_id": "../x"},
    {"run_id": "r_bad id"},
    {"run_id": "r_other_run"},  # the events belong to another run
    {"run_id": None},
    {"exported_at": "yesterday"},
    {"exported_at": 7},
    {"counts": {"events": -1, "archive_records": 3, "versions": 5, "manifest_revisions": 4}},
    {"counts": {"events": 18.5, "archive_records": 3, "versions": 5, "manifest_revisions": 4}},
    {"counts": {"events": True, "archive_records": 3, "versions": 5, "manifest_revisions": 4}},
    {"counts": {"events": "18", "archive_records": 3, "versions": 5, "manifest_revisions": 4}},
    {"counts": {"events": 18, "archive_records": 3, "versions": 5}},
    {"counts": {"events": 19, "archive_records": 3, "versions": 5, "manifest_revisions": 4}},
    {"counts": {"events": 18, "archive_records": 2, "versions": 5, "manifest_revisions": 4}},
    {"counts": {"events": 18, "archive_records": 3, "versions": 6, "manifest_revisions": 4}},
    {"counts": {"events": 18, "archive_records": 3, "versions": 5, "manifest_revisions": 3}},
    {"counts": [18, 3, 5, 4]},
    {"entries": []},
    {"entries": {"events.jsonl": "not hex"}},
    {"archive_head": {"seq": 3, "hash": "zz"}},
    {"archive_head": {"seq": 2, "hash": "0" * 64}},
    {"archive_head": None},
]


@pytest.mark.parametrize("changes", BAD_META, ids=[str(i) for i in range(len(BAD_META))])
def test_FR_MEM_10_a_bundle_json_with_a_wrong_shape_or_wrong_numbers_is_refused(src, tmp_path, changes) -> None:
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, edited(do_export(src), _set_meta(**changes)))
    assert_nothing_imported(dest)


# --- caps -----------------------------------------------------------------------------------------------------------


def test_FR_MEM_10_default_limits_are_finite_and_a_whole_world_fits() -> None:
    default = rb().DEFAULT_LIMITS
    fields = {f.name: getattr(default, f.name) for f in dataclasses.fields(default)}
    assert set(fields) == {
        "max_bundle_bytes",
        "max_uncompressed_bytes",
        "max_entries",
        "max_events",
        "max_archive_records",
        "max_versions",
    }
    assert all(type(v) is int and v > 0 for v in fields.values())
    assert fields["max_uncompressed_bytes"] >= 200 * MB, "a world's 200,000,000 bytes (AR-04) plus its records fit"
    assert rb().Limits() == default
    with pytest.raises(dataclasses.FrozenInstanceError):
        default.max_events = 1  # type: ignore[misc]


def _boundaries(entries: dict[str, bytes], bundle: bytes) -> dict[str, int]:
    return {
        "max_bundle_bytes": len(bundle),
        "max_uncompressed_bytes": sum(len(v) for v in entries.values()),
        "max_entries": len(entries),
        "max_events": len(lines_of(entries[EVENTS])),
        "max_archive_records": len(lines_of(entries[ARCHIVE])),
        "max_versions": len(names(entries, "/record.json")),
    }


@pytest.mark.parametrize(
    "cap",
    ["max_bundle_bytes", "max_uncompressed_bytes", "max_entries", "max_events", "max_archive_records", "max_versions"],
)
def test_FR_MEM_10_import_accepts_a_bundle_exactly_at_a_cap_and_refuses_one_over(src, tmp_path, cap) -> None:
    bundle = do_export(src)
    at = _boundaries(unpack(bundle), bundle)[cap]
    over = make_dest(tmp_path, src.layout, name="over", world="w_over")
    refused_and_nothing_written(over, bundle, limits=limits(**{cap: at - 1}))
    assert_nothing_imported(over)
    exact = make_dest(tmp_path, src.layout, name="exact", world="w_exact")
    do_import(exact, bundle, limits=limits(**{cap: at}))
    assert_replayed_identically(src, exact)


@pytest.mark.parametrize(
    "cap",
    ["max_bundle_bytes", "max_uncompressed_bytes", "max_entries", "max_events", "max_archive_records", "max_versions"],
)
def test_FR_MEM_10_export_refuses_what_import_would_refuse_and_writes_nothing(src, cap) -> None:
    bundle = do_export(src)
    at = _boundaries(unpack(bundle), bundle)[cap]
    with pytest.raises(refused_type()):
        do_export(src, limits=limits(**{cap: at - 1}))
    assert do_export(src, limits=limits(**{cap: at})) == bundle, "at the cap the same bundle comes out"


def test_FR_MEM_10_a_zip_bomb_is_refused_without_inflating_it(src, tmp_path) -> None:
    entries = unpack(do_export(src))
    entries["archive.jsonl"] = b"\x00" * (64 * MB)  # deflates to about 64 KB
    reindex(entries)
    recount(entries)
    bundle = raw_pack(list(entries.items()))
    assert len(bundle) < 2 * MB
    dest = make_dest(tmp_path, src.layout)
    before = dest.snapshot()
    tracemalloc.start()
    try:
        with pytest.raises(refused_type()):
            do_import(dest, bundle, limits=limits(max_uncompressed_bytes=1 * MB))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * MB, f"the bomb was inflated in memory ({peak} bytes at peak)"
    assert dest.snapshot() == before
