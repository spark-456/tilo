"""FR-MEM-10: export a run as a bundle and re-import it (PRD 13.4 emergency fallback, 13.5 "replay is identical").

A bundle is a deterministic ZIP with a closed set of entries (layout pinned in services/harness/tests/API_FR_MEM_10.md):
`bundle.json` (format, version, run id, export time, counts, archive head, a SHA-256 per entry), `events.jsonl`,
`archive.jsonl` and `artifacts/<id>/v<NNNNNN>/{record.json,content,manifests.json}`. Export is read-only and refuses
what it cannot vouch for. Import treats every byte as untrusted: everything is validated first (a dry run of every
version, manifest and event through scratch stores), then, under one lock per world and per (org, run), artifacts,
archive lines and events are written, in that order. The importer's scope, world and screener decide. Only
`expected_sha256` authenticates a bundle: its index and archive chain can be recomputed by whoever edits it.
Messages hold rule names and counts, never content.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import math
import re
import stat
import struct
import threading
import zipfile
import zlib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from tilo_archive import RunArchive
from tilo_archive.archive import Store, verify_chain
from tilo_archive.record import VALID_KINDS, ZERO_HASH, canonical_json
from tilo_memory.artifacts import (
    TEXT_TYPES,
    ArtifactError,
    ArtifactNotFound,
    ArtifactStore,
    MemoryBlobBackend,
    MemoryMetaBackend,
    Scope,
)

from tilo_harness.store import MemoryStore
from tilo_harness.validator import EventRejected
from tilo_harness.writer import WorldWriter, format_ts

BUNDLE_FORMAT, BUNDLE_VERSION = "tilo.run-bundle", "1.0"
META, EVENTS, ARCHIVE = "bundle.json", "events.jsonl", "archive.jsonl"
_PARTS = frozenset({"record.json", "content", "manifests.json"})
_ENTRY = re.compile(r"artifacts/(art_[0-9A-Za-z_]{1,48})/v([0-9]{6})/(record\.json|content|manifests\.json)")
_RUN = re.compile(r"r_[0-9A-Za-z_]{1,48}")
_HEX = re.compile(r"[0-9a-f]{64}")
_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z")
_CODE = re.compile(r"EV-[0-9]{2}|schema")
_RECORDING = ("artifact.created", "artifact.versioned", "artifact.rolled_back")
_DIGESTS = frozenset({"content_sha256", "fingerprint", "hash", "prev_hash"})  # skipped only when they hold a digest
_DIGEST = re.compile(r"(sha256:)?[0-9a-f]{64}")
_COUNTS = ("events", "archive_records", "versions", "manifest_revisions")
_META_KEYS = frozenset({"format", "version", "run_id", "exported_at", "counts", "archive_head", "entries"})
_RECORD_KEYS = frozenset({"v", "run_id", "seq", "kind", "ts", "payload", "prev_hash", "hash"})  # RunArchive's
_EOCD, _LOCAL = struct.Struct("<4s4H2LH"), struct.Struct("<4s5H3L2H")
_CD_ENTRY_MAX = 256  # bytes a bundle's central-directory entry can need (fixed part, closed-set name, small extra)

Ref = tuple[str, int]


@dataclass(frozen=True)
class Limits:
    """Bundle caps (the PRD names none: defaults logged in docs/open-questions.md). Exactly at a cap passes."""

    max_bundle_bytes: int = 300_000_000
    max_uncompressed_bytes: int = 300_000_000  # a whole world (AR-04: 200,000,000 bytes) plus its records
    max_entries: int = 30_003  # three per version plus bundle.json, events.jsonl and archive.jsonl
    max_events: int = 200_000
    max_archive_records: int = 100_000
    max_versions: int = 10_000


DEFAULT_LIMITS = Limits()


class BundleError(Exception):
    """An export or import did not complete."""


class BundleRefused(BundleError, ValueError):
    """The bundle (or the export) breaks a rule; nothing was written. The message never holds content."""


@dataclass(frozen=True)
class ImportResult:
    run_id: str
    org_id: str
    world_id: str
    events: int
    versions: int
    manifest_revisions: int
    archive_records: int
    already_imported: bool
    verified: bool = False  # true only when `expected_sha256` was given and matched (BQ-MEM10-3)


@dataclass
class _Version:
    record: dict[str, Any]
    content: bytes
    revisions: list[dict[str, Any]]


@dataclass
class _Bundle:
    run_id: str
    exported_at: datetime
    events: list[dict[str, Any]]
    archive: list[str]
    records: list[dict[str, Any]]
    versions: dict[Ref, _Version]


def _refuse(why: str) -> BundleRefused:
    return BundleRefused(f"FR-MEM-10: {why}")


def _ref(ref: Ref) -> dict[str, Any]:
    return {"artifact_id": ref[0], "version": ref[1]}


def _dumps(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def _strings(value: Any) -> Iterator[str]:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for key, child in item.items():
                yield str(key)
                if not (key in _DIGESTS and isinstance(child, str) and _DIGEST.fullmatch(child)):
                    stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)


def _scan(redact: Callable[[str], str], *values: Any) -> None:
    """MF-06 and SEC-01: refuse when the secret redactor would change any string (or fails). Fail closed."""
    for text in {s for value in values for s in _strings(value)}:
        try:
            changed = redact(text) != text
        except Exception:  # noqa: BLE001 - the redactor's error may echo the secret
            changed = True
        if changed:
            raise _refuse("a string holds what the secret redactor removes, or the redactor failed")


def _check_stream(events: Sequence[Any], run_id: Any) -> None:
    """One whole run of one world: non-empty, `seq` exactly 1..n in order, one world id, every run id `run_id`."""
    if type(run_id) is not str or _RUN.fullmatch(run_id) is None:
        raise _refuse("the run id is malformed")
    if not events or not all(isinstance(e, dict) for e in events):
        raise _refuse("the event stream is empty or not a list of objects")
    worlds = {e.get("world_id") for e in events}
    seqs_ok = all(type(e.get("seq")) is int and e["seq"] == i for i, e in enumerate(events, start=1))
    if len(worlds) != 1 or type(next(iter(worlds))) is not str or not seqs_ok:
        raise _refuse("the events are not one world's stream from seq 1 with no gap")
    if any(e.get("run_id") != run_id for e in events):
        raise _refuse("an event belongs to another run")


def _recorded(events: Sequence[dict[str, Any]]) -> dict[Ref, dict[str, Any]]:
    """The versions the events record (EV-15), each with the event that recorded it."""
    out: dict[Ref, dict[str, Any]] = {}
    for event in events:
        if event["type"] in _RECORDING:
            ref = event["data"]["artifact"]
            out[(ref["artifact_id"], ref["version"])] = event
    return out


def _check_limits(limits: Limits, **sizes: int) -> None:
    for name, value in sizes.items():
        if value > getattr(limits, name):
            raise _refuse(f"over the {name} cap")


def _stamp(text: Any) -> datetime:
    if type(text) is not str or _STAMP.fullmatch(text) is None:
        raise _refuse("a time is not a timestamp")
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


# --- export ---------------------------------------------------------------------------------------------------------


def export_run(
    *,
    events: Sequence[dict[str, Any]],
    artifacts: ArtifactStore,
    scope: Scope,
    archive: RunArchive | None,
    run_id: str,
    redact: Callable[[str], str],
    clock: Callable[[], datetime],
    limits: Limits = DEFAULT_LIMITS,
) -> bytes:
    """The run as a bundle. Read-only on every store; the same run and clock give the same bytes."""
    events = list(events)
    _check_stream(events, run_id)
    versions = {ref: _read_version(artifacts, scope, ref) for ref in sorted(_recorded(events))}
    records = archive.records() if archive is not None else []
    head = archive.head() if archive is not None else (0, ZERO_HASH)
    if any(r.get("run_id") != run_id for r in records) or verify_chain(records, head):
        raise _refuse("the raw archive is not this run's intact chain")
    try:
        texts = [v.content.decode("utf-8") for v in versions.values() if v.record["media_type"] in TEXT_TYPES]
    except UnicodeDecodeError:
        raise _refuse("a text version is not UTF-8") from None
    _scan(redact, events, records, [v.revisions for v in versions.values()], texts)
    entries = {
        EVENTS: b"".join(_dumps(e) + b"\n" for e in events),
        ARCHIVE: b"".join(_dumps(r) + b"\n" for r in records),
    }
    for (art, number), version in versions.items():
        base = f"artifacts/{art}/v{number:06d}"
        entries[f"{base}/record.json"] = _dumps(version.record)
        entries[f"{base}/content"] = version.content
        entries[f"{base}/manifests.json"] = _dumps(version.revisions)
    counts = [len(events), len(records), len(versions), sum(len(v.revisions) for v in versions.values())]
    entries[META] = _dumps(
        {
            "format": BUNDLE_FORMAT,
            "version": BUNDLE_VERSION,
            "run_id": run_id,
            "exported_at": format_ts(clock()),
            "counts": dict(zip(_COUNTS, counts, strict=True)),
            "archive_head": {"seq": head[0], "hash": head[1]},
            "entries": {name: hashlib.sha256(data).hexdigest() for name, data in entries.items()},
        }
    )
    bundle = _zip(entries)
    _check_limits(
        limits,
        max_bundle_bytes=len(bundle),
        max_uncompressed_bytes=sum(len(data) for data in entries.values()),
        max_entries=len(entries),
        max_events=counts[0],
        max_archive_records=counts[1],
        max_versions=counts[2],
    )
    return bundle


def _read_version(artifacts: ArtifactStore, scope: Scope, ref: Ref) -> _Version:
    """A recorded version as the scope holds it, `sources` dropped (AR-06); absent, corrupt or unreadable refuses."""
    try:
        head = artifacts.head(scope, _ref(ref))
        if head is None:
            raise _refuse("the scope does not hold a version the events record")
        content = bytes(artifacts.read(scope, _ref(ref)))  # AR-01: re-hashed
        try:
            revisions = artifacts.manifest_revisions(scope, _ref(ref))
        except ArtifactNotFound:
            revisions = []
    except BundleRefused:
        raise
    except Exception:  # noqa: BLE001 - corrupt blob, backend error: the export cannot vouch for it
        raise _refuse("a recorded version could not be read intact") from None
    return _Version(dict(head.record, sources=[]), content, revisions)


def _zip(entries: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type, info.create_system, info.external_attr = zipfile.ZIP_DEFLATED, 3, 0o100644 << 16
            archive.writestr(info, entries[name])
    return out.getvalue()


# --- import ---------------------------------------------------------------------------------------------------------

_LOCKS: dict[tuple[str, ...], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock(*key: str) -> threading.Lock:
    """One in-process lock per key (a world, or an org's run archive). Across processes the writer's lease holds
    the world; two processes importing one run into two worlds of one org at once are not serialised (BQ-MEM10-2)."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def import_run(
    bundle: bytes,
    *,
    writer: WorldWriter,
    artifacts: ArtifactStore,
    scope: Scope,
    archive_store: Store,
    redact: Callable[[str], str],
    expected_sha256: str | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> ImportResult:
    """Validates the whole bundle, then writes artifacts and manifests, archive lines, and events last."""
    if not isinstance(scope, Scope) or (scope.org_id, scope.world_id) != (writer.org_id, writer.world_id):
        raise _refuse("the scope is not the writer's org and world")
    if not isinstance(bundle, bytes):
        raise _refuse("a bundle is bytes")
    if expected_sha256 is not None and (
        type(expected_sha256) is not str or hashlib.sha256(bundle).hexdigest() != expected_sha256
    ):
        raise _refuse("the bundle's SHA-256 is not the expected one")
    try:
        parsed = _validate(bundle, writer, scope, redact, limits)
    except BundleRefused:
        raise
    except ArtifactError as error:  # ArtifactError messages hold ids and rule names only
        raise _refuse(f"a version is refused ({error})") from None
    except Exception:  # noqa: BLE001 - any other failure on untrusted bytes is a refusal, never a crash
        raise _refuse("the bundle is malformed") from None
    with _lock("world", writer.org_id, writer.world_id), _lock("archive", scope.org_id, parsed.run_id):
        return _commit(parsed, writer, artifacts, scope, archive_store, authenticated=expected_sha256 is not None)


def _commit(
    parsed: _Bundle,
    writer: WorldWriter,
    artifacts: ArtifactStore,
    scope: Scope,
    archive_store: Store,
    *,
    authenticated: bool,
) -> ImportResult:
    """Checks against the importer's own stores, then the writes; the caller holds the world and archive locks."""
    run_id, events, lines, versions = parsed.run_id, parsed.events, parsed.archive, parsed.versions
    revisions = sum(len(v.revisions) for v in versions.values())
    held = writer.held_prefix(events)
    if held is None:
        raise _refuse("the world holds events that are not this run's")
    done: dict[Ref, int] = {}
    for ref, version in versions.items():
        head = artifacts.head(scope, _ref(ref))
        if head is None:
            continue
        if head.record["content_sha256"] != version.record["content_sha256"]:
            raise _refuse("the scope holds another version under an id the bundle names")
        try:
            have = artifacts.manifest_revisions(scope, _ref(ref))
        except ArtifactNotFound:
            have = []
        if have != version.revisions[: len(have)]:
            raise _refuse("the scope holds other manifest revisions for a version the bundle names")
        done[ref] = len(have)
    stored_lines = archive_store.read_lines(scope.org_id, run_id)
    if stored_lines != lines[: len(stored_lines)]:
        raise _refuse("another raw-archive chain is stored for this org and run")
    result = ImportResult(
        run_id, scope.org_id, scope.world_id, len(events), len(versions), revisions, len(lines), False, authenticated
    )
    if held == len(events):  # the world holds the whole run: nothing is written, and nothing may be missing
        if stored_lines != lines or done != {ref: len(v.revisions) for ref, v in versions.items()}:
            raise _refuse("the world holds this run but its artifact store or raw archive lacks part of it")
        return dataclasses.replace(result, already_imported=True)
    if stored_lines and len(stored_lines) < len(lines) and not authenticated:
        # It may be another world's live chain of this org and run: appending after it would poison it for good.
        raise _refuse("a partial raw-archive chain is stored for this run; only an import with expected_sha256 may")

    new: list[Ref] = []
    try:
        for ref in sorted(versions):
            version = versions[ref]
            if artifacts.import_version(scope, version.record, version.content).written:
                new.append(ref)
            for revision in version.revisions[done.get(ref, 0) :]:
                artifacts.add_manifest(
                    scope, _ref(ref), revision["manifest"], stage=revision["stage"], cause=revision["cause"]
                )
        for line in lines[len(stored_lines) :]:
            archive_store.append_line(scope.org_id, run_id, line)
        if writer.held_prefix(events) != held:
            raise _refuse("the world changed during the import")
    except BaseException as error:
        _roll_back(artifacts, scope, new)
        if isinstance(error, ArtifactError):
            raise _refuse(f"a version is refused ({error})") from None
        raise
    try:
        for event in events[held:]:  # last: an artifact event is never written for a version that is not stored
            writer.append(event)
    except EventRejected:
        raise BundleError("FR-MEM-10: the world changed while the events were written; a prefix is in place") from None
    return result


def _roll_back(artifacts: ArtifactStore, scope: Scope, refs: list[Ref]) -> None:
    """Best effort: removes what this call stored, by the store's own delete (record, blob and manifests)."""
    retention = artifacts.retention()
    for art, number in refs:
        try:
            retention.delete(f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{art}/versions/{number:06d}")
        except Exception:  # noqa: BLE001, S110 - the original error is the one to raise
            pass


def _validate(
    bundle: bytes, writer: WorldWriter, scope: Scope, redact: Callable[[str], str], limits: Limits
) -> _Bundle:
    """Everything that needs no read of the importer's stores, in full, before any write."""
    parsed = _parse(_read_zip(bundle, limits), limits)
    parsed.events = [dict(e, world_id=writer.world_id) for e in parsed.events]
    _scan(redact, parsed.events, parsed.records)
    dry = WorldWriter(
        MemoryStore(),
        org_id=writer.org_id,
        world_id=writer.world_id,
        run_id=parsed.run_id,
        layout=writer.layout,
        writer_id="bundle-dry-run",
    )
    dry.open()
    for event in parsed.events:  # EV-01 to EV-15 against the importer's layout
        try:
            dry.append(event)
        except EventRejected as error:
            codes = sorted({c for p in error.problems if (c := p.split(":", 1)[0]) and _CODE.fullmatch(c)})
            raise _refuse(f"event seq {event['seq']} is refused ({', '.join(codes) or 'rules'})") from None
    recorded = _recorded(parsed.events)
    if set(recorded) != set(parsed.versions):
        raise _refuse("the versions carried are not the versions the events record")
    for ref, event in recorded.items():
        data, record = event["data"], parsed.versions[ref].record
        if "content_sha256" in data and any(
            data[k] != record[k] for k in ("content_sha256", "media_type", "size_bytes")
        ):
            raise _refuse("a record does not match the artifact.created event that names it")
    scratch = ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: parsed.exported_at,  # so a record from after the export is refused
        redactor=redact,
        archive_lookup=lambda _scope, _ref: None,
        alert_sink=lambda _alert: None,
    )
    for ref in sorted(parsed.versions):  # AR-01 to AR-08 and MF-06, as the real import will apply them
        version = parsed.versions[ref]
        scratch.import_version(scope, version.record, version.content)
        for revision in version.revisions:
            scratch.add_manifest(
                scope, _ref(ref), revision["manifest"], stage=revision["stage"], cause=revision["cause"]
            )
        if version.revisions and scratch.manifest_revisions(scope, _ref(ref)) != version.revisions:
            raise _refuse("manifest revisions are not numbered 1..k")
    return parsed


def _read_zip(bundle: bytes, limits: Limits) -> dict[str, bytes]:
    """The entries, after the end record, every name, type and declared size are checked. The end record is read
    before zipfile builds its entry list (no comment, no ZIP64, a bounded central directory), and every entry is
    inflated by `_inflate`, never past its declared size."""
    _check_limits(limits, max_bundle_bytes=len(bundle))
    if len(bundle) < _EOCD.size:
        raise _refuse("not a ZIP")
    sig, disk, cd_disk, here, total, cd_size, _offset, comment = _EOCD.unpack_from(bundle, len(bundle) - _EOCD.size)
    if sig != b"PK\x05\x06" or comment or disk or cd_disk or here != total or bundle[-42:-38] == b"PK\x06\x07":
        raise _refuse("not a plain bundle ZIP (a comment, several disks or ZIP64)")
    _check_limits(limits, max_entries=total)
    if cd_size > total * _CD_ENTRY_MAX:
        raise _refuse("the central directory is larger than its entries need")
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        infos = archive.infolist()
        names = [info.orig_filename for info in infos]
        if len(infos) != total or len(set(names)) != len(names):
            raise _refuse("the entry count is wrong or an entry name repeats")
        for info in infos:
            match = _ENTRY.fullmatch(info.filename)
            if (
                info.orig_filename != info.filename
                or (info.filename not in (META, EVENTS, ARCHIVE) and (match is None or int(match[2]) < 1))
                or info.external_attr & 0x10
                or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                or info.flag_bits & 0x1
                or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
            ):
                raise _refuse("an entry is not a plain file of the bundle's closed set")
    _check_limits(limits, max_uncompressed_bytes=sum(info.file_size for info in infos))
    return {info.filename: _inflate(bundle, info) for info in infos}


def _inflate(bundle: bytes, info: zipfile.ZipInfo) -> bytes:
    """One entry's bytes, inflated to at most its declared size + 1: more, less or another CRC refuses."""
    start = info.header_offset
    sig, _ver, flags, method, _t, _d, _crc, _csize, _size, name_len, extra_len = _LOCAL.unpack_from(bundle, start)
    body = start + _LOCAL.size + name_len + extra_len
    raw = memoryview(bundle)[body : body + info.compress_size]
    name = bundle[start + _LOCAL.size : start + _LOCAL.size + name_len]
    if sig != b"PK\x03\x04" or flags & 1 or method != info.compress_type or len(raw) != info.compress_size:
        raise _refuse("an entry's local header does not match the central directory")
    if name != info.orig_filename.encode("ascii"):
        raise _refuse("an entry's local header does not match the central directory")
    if method == zipfile.ZIP_STORED:
        data = bytes(raw)
    else:
        inflater = zlib.decompressobj(-15)
        data = inflater.decompress(raw, info.file_size + 1)  # never more than declared + 1 in memory
        if not inflater.eof or inflater.unconsumed_tail or inflater.unused_data:
            raise _refuse("an entry inflates to another size than it declares")
    if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
        raise _refuse("an entry inflates to another size or CRC than it declares")
    return data


def _json(data: bytes | str) -> Any:
    def finite(text: str) -> float:
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("not finite")
        return value

    def constant(_name: str) -> Any:
        raise ValueError("NaN and Infinity are not JSON")

    text = data.decode("utf-8") if isinstance(data, bytes) else data
    return json.loads(text, parse_float=finite, parse_constant=constant)


def _lines(data: bytes, cap: int, name: str) -> list[str]:
    text = data.decode("utf-8")
    if text and not text.endswith("\n"):
        raise _refuse(f"{name} does not end with a newline")
    lines = text.split("\n")[:-1] if text else []
    if len(lines) > cap:
        raise _refuse(f"over the {name} cap")
    if any(not line for line in lines):
        raise _refuse(f"{name} holds a blank line")
    return lines


def _parse(entries: dict[str, bytes], limits: Limits) -> _Bundle:
    if not {META, EVENTS, ARCHIVE} <= set(entries):
        raise _refuse("an entry is missing")
    meta = _json(entries[META])
    if not isinstance(meta, dict) or set(meta) != _META_KEYS:
        raise _refuse("bundle.json does not have exactly the bundle's keys")
    if meta["format"] != BUNDLE_FORMAT or meta["version"] != BUNDLE_VERSION:
        raise _refuse("another bundle format or version")
    run_id, exported_at, index = meta["run_id"], _stamp(meta["exported_at"]), meta["entries"]
    if type(run_id) is not str or _RUN.fullmatch(run_id) is None:
        raise _refuse("the run id is malformed")
    if not isinstance(index, dict) or set(index) != set(entries) - {META}:
        raise _refuse("the index does not list exactly the entries")
    if any(index[name] != hashlib.sha256(data).hexdigest() for name, data in entries.items() if name != META):
        raise _refuse("an entry does not match its SHA-256 in the index")

    events = [_json(line) for line in _lines(entries[EVENTS], limits.max_events, "max_events")]
    archive = _lines(entries[ARCHIVE], limits.max_archive_records, "max_archive_records")
    records = [_json(line) for line in archive]
    if not all(isinstance(r, dict) and canonical_json(r) == line for r, line in zip(records, archive, strict=True)):
        raise _refuse("an archive line is not a canonical record")
    for record in records:  # RunArchive's exact shape: no extra key can carry anything past the scan's reach
        if set(record) != _RECORD_KEYS or record["v"] != "1.0" or record["kind"] not in VALID_KINDS:
            raise _refuse("an archive record does not have the raw archive's shape")
        _stamp(record["ts"])
    parts: dict[Ref, dict[str, bytes]] = {}
    for name, data in entries.items():
        if (match := _ENTRY.fullmatch(name)) is not None:
            parts.setdefault((match[1], int(match[2])), {})[match[3]] = data
    _check_limits(limits, max_versions=len(parts))
    versions = {ref: _version(ref, found, run_id) for ref, found in parts.items()}

    counts, head = meta["counts"], meta["archive_head"]
    real = [len(events), len(records), len(versions), sum(len(v.revisions) for v in versions.values())]
    if not isinstance(counts, dict) or set(counts) != set(_COUNTS):
        raise _refuse("counts do not have exactly the bundle's keys")
    if any(type(counts[k]) is not int or counts[k] != n for k, n in zip(_COUNTS, real, strict=True)):
        raise _refuse("counts do not match the entries")
    if not isinstance(head, dict) or set(head) != {"seq", "hash"} or type(head["seq"]) is not int:
        raise _refuse("archive_head is malformed")
    if type(head["hash"]) is not str or _HEX.fullmatch(head["hash"]) is None:
        raise _refuse("archive_head is malformed")
    if any(r["run_id"] != run_id for r in records) or verify_chain(records, (head["seq"], head["hash"])):
        raise _refuse("the raw-archive chain does not verify against archive_head")
    _check_stream(events, run_id)
    return _Bundle(run_id, exported_at, events, archive, records, versions)


def _version(ref: Ref, found: dict[str, bytes], run_id: str) -> _Version:
    if set(found) != _PARTS:
        raise _refuse("a version directory lacks an entry")
    record, revisions = _json(found["record.json"]), _json(found["manifests.json"])
    if not isinstance(record, dict) or record.get("artifact") != _ref(ref) or record.get("run_id") != run_id:
        raise _refuse("a record does not name the version its path names, or another run")
    if not isinstance(revisions, list) or not all(
        isinstance(r, dict) and r.get("n") == n and type(r.get("n")) is int for n, r in enumerate(revisions, start=1)
    ):
        raise _refuse("manifest revisions are not numbered 1..k")
    return _Version(record, found["content"], revisions)
