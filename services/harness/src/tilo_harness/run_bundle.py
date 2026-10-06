"""FR-MEM-10: export a run as a bundle and re-import it (PRD 13.4 emergency fallback, 13.5 "replay is identical").

A bundle is a deterministic ZIP with a closed set of entries (layout pinned in services/harness/tests/API_FR_MEM_10.md):
`bundle.json` (format, version, run id, export time, counts, archive head, a SHA-256 per entry), `events.jsonl`,
`archive.jsonl` and `artifacts/<id>/v<NNNNNN>/{record.json,content,manifests.json}`. Export is read-only and refuses
what it cannot vouch for. Import treats every byte as untrusted: everything is validated first (a dry run of every
version, manifest and event through scratch stores), then artifacts, archive lines and events are written, in that
order. The importer's scope, world and screener decide. Messages hold rule names and counts, never content.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import stat
import zipfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from typing import Any

from tilo_archive import RunArchive
from tilo_archive.archive import Store, verify_chain
from tilo_archive.record import ZERO_HASH, canonical_json
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
_DIGESTS = frozenset({"content_sha256", "fingerprint"})  # hex digests are not shown to the redactor (MF-06)
_COUNTS = ("events", "archive_records", "versions", "manifest_revisions")
_META_KEYS = frozenset({"format", "version", "run_id", "exported_at", "counts", "archive_head", "entries"})
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)

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


@dataclass
class _Version:
    record: dict[str, Any]
    content: bytes
    revisions: list[dict[str, Any]]


@dataclass
class _Bundle:
    run_id: str
    events: list[dict[str, Any]]
    archive: list[str]
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
                if key not in _DIGESTS:
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
    _scan(redact, events, [r["payload"] for r in records], [v.revisions for v in versions.values()], texts)
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
    sizes = (len(bundle), sum(len(data) for data in entries.values()), len(entries), *counts[:3])
    _check_limits(limits, **{f.name: size for f, size in zip(fields(Limits), sizes, strict=True)})
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
    run_id, events, lines, versions = parsed.run_id, parsed.events, parsed.archive, parsed.versions

    # Checks against the importer's own stores (reads only; an outage here propagates as it is).
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

    new: list[Ref] = []
    try:
        for ref in sorted(versions):
            version = versions[ref]
            if ref not in done:
                new.append(ref)
            artifacts.import_version(scope, version.record, version.content)
            for revision in version.revisions[done.get(ref, 0) :]:
                artifacts.add_manifest(
                    scope, _ref(ref), revision["manifest"], stage=revision["stage"], cause=revision["cause"]
                )
        for line in lines[len(stored_lines) :]:
            archive_store.append_line(scope.org_id, run_id, line)
    except BaseException as error:
        _roll_back(artifacts, scope, new)
        if isinstance(error, ArtifactError):
            raise _refuse(f"a version is refused ({error})") from None
        raise
    for event in events[held:]:  # last: an artifact event is never written for a version that is not stored
        writer.append(event)
    revisions = sum(len(v.revisions) for v in versions.values())
    counts = (len(events), len(versions), revisions, len(lines), held == len(events))
    return ImportResult(run_id, scope.org_id, scope.world_id, *counts)


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
    _scan(redact, parsed.events, [json.loads(line)["payload"] for line in parsed.archive])
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
        clock=lambda: _EPOCH,
        redactor=redact,
        archive_lookup=lambda _scope, _ref: None,
        alert_sink=lambda _alert: None,
    )
    for ref in sorted(parsed.versions):  # AR-01 to AR-07 and MF-06, as the real import will apply them
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
    """The entries, after every name, type and declared size is checked; nothing is inflated before that."""
    _check_limits(limits, max_bundle_bytes=len(bundle))
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        infos = archive.infolist()
        _check_limits(limits, max_entries=len(infos))
        names = [info.orig_filename for info in infos]
        if len(set(names)) != len(names):
            raise _refuse("an entry name repeats")
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
        return {info.filename: archive.read(info) for info in infos}


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
    run_id, stamp, index = meta["run_id"], meta["exported_at"], meta["entries"]
    if type(run_id) is not str or _RUN.fullmatch(run_id) is None:
        raise _refuse("the run id is malformed")
    if type(stamp) is not str or _STAMP.fullmatch(stamp) is None:
        raise _refuse("exported_at is not a timestamp")
    datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    if not isinstance(index, dict) or set(index) != set(entries) - {META}:
        raise _refuse("the index does not list exactly the entries")
    if any(index[name] != hashlib.sha256(data).hexdigest() for name, data in entries.items() if name != META):
        raise _refuse("an entry does not match its SHA-256 in the index")

    events = [_json(line) for line in _lines(entries[EVENTS], limits.max_events, "max_events")]
    archive = _lines(entries[ARCHIVE], limits.max_archive_records, "max_archive_records")
    records = [_json(line) for line in archive]
    if not all(isinstance(r, dict) and canonical_json(r) == line for r, line in zip(records, archive, strict=True)):
        raise _refuse("an archive line is not a canonical record")
    parts: dict[Ref, dict[str, bytes]] = {}
    for name, data in entries.items():
        if (match := _ENTRY.fullmatch(name)) is not None:
            parts.setdefault((match[1], int(match[2])), {})[match[3]] = data
    _check_limits(limits, max_versions=len(parts))
    versions = {ref: _version(ref, found) for ref, found in parts.items()}

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
    if any(r.get("run_id") != run_id for r in records) or verify_chain(records, (head["seq"], head["hash"])):
        raise _refuse("the raw-archive chain does not verify against archive_head")
    _check_stream(events, run_id)
    return _Bundle(run_id, events, archive, versions)


def _version(ref: Ref, found: dict[str, bytes]) -> _Version:
    if set(found) != _PARTS:
        raise _refuse("a version directory lacks an entry")
    record, revisions = _json(found["record.json"]), _json(found["manifests.json"])
    if not isinstance(record, dict) or record.get("artifact") != _ref(ref):
        raise _refuse("a record does not name the version its path names")
    if not isinstance(revisions, list) or not all(
        isinstance(r, dict) and r.get("n") == n and type(r.get("n")) is int for n, r in enumerate(revisions, start=1)
    ):
        raise _refuse("manifest revisions are not numbered 1..k")
    return _Version(record, found["content"], revisions)
