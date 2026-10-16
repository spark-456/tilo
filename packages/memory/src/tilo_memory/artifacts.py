"""The artifact store (FR-MEM-06, FR-MEM-12; ADR-0018 sections 2 and 3; contracts/artifact.rules.md AR-01 to AR-08).

One immutable, hash-checked, owner-scoped version per put. Hashing, caps, scoping, versions and idempotency live here
once; the backends are thin (create-only documents and blobs). Every id, key and ref is matched whole with `fullmatch`
before any path or blob key is derived (the contract's `$` lets a trailing newline through). Time comes from the
injected clock, the redactor, screener and archive are injected, and nothing here touches the network or a model.
Errors carry ids and rule names, never content.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import pathlib
import re
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

_CONTRACTS = pathlib.Path(__file__).resolve().parents[4] / "contracts"
_SCHEMA_ID = "https://contracts.tilo.example/artifact.schema.json"
TEXT_TYPES = frozenset({"text/markdown", "text/csv", "application/json"})
FILE_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "image/png",
        "image/jpeg",
    }
)
MAX_TEXT, MAX_FILE, MAX_WORLD = 2_000_000, 50_000_000, 200_000_000  # BQ-257
STAGES = ("created", "reviewed", "sent", "exported")
_DIGEST_KEYS = frozenset({"content_sha256", "fingerprint"})  # hex digests are not shown to the redactor (MF-06)
_RETRIES = 8
GRACE = timedelta(minutes=5)  # a record without its blob may be another writer's write in flight until then

_ORG, _WORLD, _OWNER = r"org_[0-9A-Za-z_]{1,48}", r"w_[0-9A-Za-z_]{1,48}", r"u_[0-9A-Za-z_]{1,48}"
_ART, _RUN, _UNIT, _AGENT = r"art_[0-9A-Za-z_]{1,48}", r"r_[0-9A-Za-z_]{1,48}", r"U[0-9]{1,4}", r"A_[0-9A-Za-z_]{1,48}"
_ID = {k: re.compile(v) for k, v in {"org": _ORG, "world": _WORLD, "owner": _OWNER, "art": _ART}.items()}
_RUN_ID, _UNIT_ID, _AGENT_ID = re.compile(_RUN), re.compile(_UNIT), re.compile(_AGENT)
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,63}")
_ARCHIVE_REF = re.compile(r"(r_[0-9A-Za-z_]{1,48})/[0-9]{1,9}")
_KEY = re.compile(rf"({_RUN}):({_UNIT}):(?:0|[1-9][0-9]{{0,3}}):[0-9]")
_FETCH_KEY = re.compile(rf"({_RUN}):({_UNIT}):(?:0|[1-9][0-9]{{0,3}}):f[0-9]")
_SEGMENT = re.compile(r"[0-9A-Za-z_]+")
_ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")
_RECORD_PATH = re.compile(rf"orgs/({_ORG})/worlds/({_WORLD})/artifacts/({_ART})/versions/([0-9]{{6}})")


class ArtifactError(Exception):
    """Base of every store error. Messages hold ids and rule names only."""


class ArtifactNotFound(ArtifactError, LookupError):
    """No such version in this Scope (never existed, or another org, world or owner: the same answer)."""


class ArtifactCorrupt(ArtifactError):
    """The stored bytes do not match the record (AR-01)."""


class ArtifactBusy(ArtifactError):
    """Retryable: a record without its blob is younger than the grace window, so its writer may still be finishing."""

    retryable = True


class ArtifactRefused(ArtifactError, ValueError):
    """The call breaks a rule; nothing was stored."""


def _refuse(rule: str, what: str) -> ArtifactRefused:
    return ArtifactRefused(f"{rule}: {what}")


# --- value types ------------------------------------------------------------------------------------------------


def _check_scope(scope: Scope) -> None:
    for name, pattern in (("org_id", "org"), ("world_id", "world"), ("owner", "owner")):
        value = getattr(scope, name, None)
        if type(value) is not str or _ID[pattern].fullmatch(value) is None:
            raise ValueError(f"scope {name} is not a well-formed id")


@dataclass(frozen=True)
class Scope:
    """Who a call is for. Comes from the run, never from a request."""

    org_id: str
    world_id: str
    owner: str

    def __post_init__(self) -> None:
        _check_scope(self)


@dataclass(frozen=True)
class Origin:
    kind: str  # unit | render | upload | restore | fetch
    unit: str | None = None
    agent: str | None = None


@dataclass(frozen=True)
class NewVersion:
    """What a producer may say. The store sets the id, version, screening, redaction and hash. `label` is not stored."""

    media_type: str
    content: bytes
    run_id: str
    origin: Origin
    sources: tuple[dict[str, str], ...] = ()
    idempotency_key: str | None = None
    parent: Mapping[str, Any] | None = None
    label: str | None = None
    # A producer that screened its own input in pieces may say "flagged". It can only raise the stored verdict (the
    # store takes flagged if its own screen or the hint says so) and is never stored or applied to a replay.
    screening_hint: str | None = None


@dataclass(frozen=True)
class StoredVersion:
    doc: dict[str, Any] = field(repr=False)
    written: bool = field(default=False, compare=False)  # this call stored it (FR-MEM-10 rolls back only its own)

    @property
    def record(self) -> dict[str, Any]:
        return copy.deepcopy(self.doc)

    @property
    def ref(self) -> dict[str, Any]:
        return {"artifact_id": self.doc["artifact"]["artifact_id"], "version": self.doc["artifact"]["version"]}

    @property
    def artifact_id(self) -> str:
        return self.doc["artifact"]["artifact_id"]

    @property
    def version(self) -> int:
        return self.doc["artifact"]["version"]


def _ref(ref: Any) -> dict[str, Any]:
    """A well-formed artifact_ref as {artifact_id, version}; ValueError otherwise (before any backend call)."""
    try:
        art, version = ref["artifact_id"], ref["version"]
    except (TypeError, KeyError):
        raise ValueError("malformed artifact ref") from None
    if type(art) is not str or _ID["art"].fullmatch(art) is None:
        raise ValueError("malformed artifact id")
    if type(version) is not int or not 1 <= version <= 999_999:
        raise ValueError("malformed artifact version")
    return {"artifact_id": art, "version": version}


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("the clock must return an aware datetime")
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _when(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _ulid() -> str:
    """26 Crockford characters from 128 random bits (no time part: the clock is read only for record times)."""
    alphabet, n = "0123456789ABCDEFGHJKMNPQRSTVWXYZ", secrets.randbits(128)
    return "".join(alphabet[(n >> shift) & 31] for shift in range(125, -1, -5))


# --- schema validation ------------------------------------------------------------------------------------------


@functools.cache
def _registry() -> Registry:
    resources = []
    for path in sorted(_CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data.get("$id") or path.resolve().as_uri(), Resource.from_contents(data, DRAFT202012)))
    return Registry().with_resources(resources)


@functools.cache
def _validator(fragment: str) -> jsonschema.protocols.Validator:
    return jsonschema.Draft202012Validator({"$ref": _SCHEMA_ID + fragment}, registry=_registry())


def _validate(fragment: str, instance: Any, what: str) -> None:
    paths = sorted(
        {"/".join(map(str, e.absolute_path)) or "(root)" for e in _validator(fragment).iter_errors(instance)}
    )
    if paths:
        raise ArtifactRefused(f"{what} does not match artifact.schema.json at: {', '.join(paths)}")


def validate_record(record: dict[str, Any]) -> None:
    """An ArtifactVersion against contracts/artifact.schema.json (not only the pydantic model)."""
    _validate("", record, "record")


def validate_revision(revision: dict[str, Any]) -> None:
    """A manifest revision against `artifact.schema.json#/$defs/manifest_revision`."""
    _validate("#/$defs/manifest_revision", revision, "manifest revision")


# --- backends ---------------------------------------------------------------------------------------------------


class MetaBackend(Protocol):
    """Create-only documents. The store takes the next version itself (highest + 1 under its lock, retried on a
    create conflict), so no extra atomic operation is needed."""

    def create(self, path: str, doc: dict[str, Any]) -> None: ...  # FileExistsError if present; never overwrites
    def get(self, path: str) -> dict[str, Any] | None: ...
    def delete(self, path: str) -> None: ...  # idempotent
    def paths(self, prefix: str = "") -> list[str]: ...


class BlobBackend(Protocol):
    def create(self, key: str, data: bytes) -> None: ...  # FileExistsError if present; never overwrites
    def read(self, key: str) -> bytes: ...  # FileNotFoundError when absent
    def delete(self, key: str) -> None: ...  # idempotent; every generation
    def keys(self, prefix: str = "") -> list[str]: ...


class MemoryMetaBackend:
    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, path: str, doc: dict[str, Any]) -> None:
        with self._lock:
            if path in self._docs:
                raise FileExistsError(path)
            self._docs[path] = copy.deepcopy(doc)

    def get(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            doc = self._docs.get(path)
        return None if doc is None else copy.deepcopy(doc)

    def delete(self, path: str) -> None:
        with self._lock:
            self._docs.pop(path, None)

    def paths(self, prefix: str = "") -> list[str]:
        with self._lock:
            return sorted(p for p in self._docs if p.startswith(prefix))


class MemoryBlobBackend:
    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def create(self, key: str, data: bytes) -> None:
        with self._lock:
            if key in self._blobs:
                raise FileExistsError(key)
            self._blobs[key] = data

    def read(self, key: str) -> bytes:
        try:
            return self._blobs[key]
        except KeyError:
            raise FileNotFoundError(key) from None

    def delete(self, key: str) -> None:
        with self._lock:
            self._blobs.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        with self._lock:
            return sorted(k for k in self._blobs if k.startswith(prefix))


class LocalDirBlobBackend:
    """One file per version under `root` (`open(path, "xb")`); a key that could leave the root is refused."""

    def __init__(self, root: pathlib.Path | str) -> None:
        self.root = pathlib.Path(root)

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> LocalDirBlobBackend:
        return cls(environ.get("TILO_ARTIFACT_DIR") or ".tilo/artifacts/")  # touches no disk

    def _path(self, key: str) -> pathlib.Path:
        parts = key.split("/") if type(key) is str else []
        if not parts or any(_SEGMENT.fullmatch(p) is None for p in parts):  # id charset only: no `.`, `\\`, `:`
            raise ValueError("unsafe blob key")
        return self.root.joinpath(*parts)

    def create(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as handle:  # raises FileExistsError: never overwrites
            handle.write(data)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)
        for parent in path.parents:  # prune the now-empty folders, never the root itself
            if parent == self.root:
                break
            try:
                parent.rmdir()
            except OSError:
                break

    def keys(self, prefix: str = "") -> list[str]:
        found = (p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())
        return sorted(k for k in found if k.startswith(prefix))


# --- the store --------------------------------------------------------------------------------------------------


def _art_prefix(scope: Scope, artifact_id: str) -> str:
    return f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{artifact_id}"


def _record_path(scope: Scope, ref: Mapping[str, Any]) -> str:
    return f"{_art_prefix(scope, ref['artifact_id'])}/versions/{ref['version']:06d}"


def _blob_key(scope: Scope, ref: Mapping[str, Any]) -> str:
    return f"{_art_prefix(scope, ref['artifact_id'])}/v{ref['version']:06d}"


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if key not in _DIGEST_KEYS:
                yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


class ArtifactStore:
    _upload_text: Callable[[bytes, str], str] | None = None

    def with_upload_text(self, convert: Callable[[bytes, str], str]) -> ArtifactStore:
        """A request-local view: the store still screens exact stored bytes, with Office text conversion first.

        No producer supplies a verdict; the configured safety provider remains authoritative.
        Backends, caps, redaction, scope checks and locks are shared; other requests are unchanged.
        """
        view = copy.copy(self)
        view._upload_text = convert
        return view

    def with_screener(self, screener: Any) -> ArtifactStore:
        """A run-local view whose verdicts come from `screener` (RESULT-LIVE: a live run's own metered safety
        provider, SEC-16). Still only a verdict on the exact stored bytes says clean (AR-07); backends, caps,
        redaction, scope checks and locks are shared; other users of the store are unchanged."""
        view = copy.copy(self)
        view._screener = screener
        return view

    def with_new_id(self, new_id: Callable[[], str]) -> ArtifactStore:
        """A request-local view that names a new artifact with `new_id` (the id is still checked as any other): for a
        producer whose artifact has a derived id, such as one morning brief per local date (ADR-0049, MO-09). Backends,
        caps, redaction, screening, scope checks and locks are shared; other users of the store are unchanged."""
        view = copy.copy(self)
        view._new_id = new_id
        return view

    def __init__(
        self,
        meta: MetaBackend,
        blobs: BlobBackend,
        *,
        clock: Callable[[], datetime],
        redactor: Callable[[str], str],
        archive_lookup: Callable[[Scope, str], str | None],
        alert_sink: Callable[[dict[str, Any]], None],
        screener: Any | None = None,
        hasher: Callable[[bytes], str] | None = None,
        record_validator: Callable[[dict[str, Any]], None] | None = None,
        new_id: Callable[[], str] | None = None,
        file_sniffer: Callable[[bytes], str] | None = None,
    ) -> None:
        self._meta, self._blobs, self._clock, self._redact = meta, blobs, clock, redactor
        self._archive, self._alert, self._screener = archive_lookup, alert_sink, screener
        self._hash = hasher or (lambda data: hashlib.sha256(data).hexdigest())
        self._validate_record = record_validator or validate_record
        self._file_sniffer = file_sniffer
        self._new_id = new_id or (lambda: "art_" + _ulid())
        self._lock = threading.RLock()
        self._alerted: set[tuple[str, str, str, int]] = set()  # corrupt versions already announced

    # -- reads ---------------------------------------------------------------------------------------------------

    def _docs(self, prefix: str) -> list[dict[str, Any]]:
        docs = (self._meta.get(p) for p in self._meta.paths(prefix) if _RECORD_PATH.fullmatch(p))
        return [d for d in docs if d is not None]

    def _find(self, scope: Scope, ref: Mapping[str, Any]) -> dict[str, Any] | None:
        doc = self._meta.get(_record_path(scope, ref))
        return doc if doc is not None and doc["owner"] == scope.owner else None  # another owner reads as absent

    def _require(self, scope: Scope, ref: Any) -> dict[str, Any]:
        _check_scope(scope)
        ref = _ref(ref)
        doc = self._find(scope, ref)
        if doc is None:
            raise ArtifactNotFound(f"no artifact {ref['artifact_id']} version {ref['version']}")
        return doc

    def head(self, scope: Scope, ref: Mapping[str, Any]) -> StoredVersion | None:
        _check_scope(scope)
        doc = self._find(scope, _ref(ref))
        return None if doc is None else StoredVersion(doc)

    def read(self, scope: Scope, ref: Mapping[str, Any]) -> bytes:
        return self._verified(scope, self._require(scope, ref))

    def _verified(self, scope: Scope, doc: dict[str, Any]) -> bytes:
        ref = doc["artifact"]
        try:
            data: bytes | None = self._blobs.read(_blob_key(scope, ref))
        except FileNotFoundError:
            data = None
        seen = (scope.org_id, scope.world_id, ref["artifact_id"], ref["version"])
        if data is not None and self._hash(data) == doc["content_sha256"] and len(data) == doc["size_bytes"]:
            with self._lock:
                self._alerted.discard(seen)
            return data
        with self._lock:  # one alert.raised per corrupt version, not one per failed read
            first = seen not in self._alerted
            self._alerted.add(seen)
        if first:
            self._announce(scope, doc)
        raise ArtifactCorrupt(f"AR-01: {ref['artifact_id']} version {ref['version']} does not match its hash")

    def _announce(self, scope: Scope, doc: dict[str, Any]) -> None:
        ref = doc["artifact"]
        alert = {
            "type": "alert.raised",
            "world_id": scope.world_id,
            "run_id": doc["run_id"],
            "artifact": {"artifact_id": ref["artifact_id"], "version": ref["version"]},
            "summary": f"artifact {ref['artifact_id']} version {ref['version']} failed its hash check",
            "data": {"alert_id": _ulid(), "card_id": None},
        }
        try:
            self._alert(alert)
        except Exception:  # noqa: BLE001 - a failing sink must not turn corruption into a different error
            pass

    def artifact_ids(self, scope: Scope, prefix: str = "art_") -> list[str]:
        """The ids named by version-record paths in this Scope's world that start with `prefix`, sorted."""
        _check_scope(scope)
        latest: dict[str, tuple[int, str]] = {}
        for path in self._meta.paths(f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/"):
            match = _RECORD_PATH.fullmatch(path)
            if match and match[1] == scope.org_id and match[2] == scope.world_id and match[3].startswith(prefix):
                version = int(match[4])
                if match[3] not in latest or version > latest[match[3]][0]:
                    latest[match[3]] = (version, path)
        found = []
        for aid, (_, path) in latest.items():
            doc = self._meta.get(path)
            if doc is not None and doc["owner"] == scope.owner:
                found.append(aid)
        return sorted(found)

    def versions(self, scope: Scope, artifact_id: str) -> list[StoredVersion]:
        _check_scope(scope)
        _ref({"artifact_id": artifact_id, "version": 1})
        docs = [d for d in self._docs(f"{_art_prefix(scope, artifact_id)}/versions/") if d["owner"] == scope.owner]
        if not docs:
            raise ArtifactNotFound(f"no artifact {artifact_id}")
        return [StoredVersion(d) for d in sorted(docs, key=lambda d: d["artifact"]["version"])]

    def source_texts(self, scope: Scope, ref: Mapping[str, Any]) -> dict[str, str]:
        """The Verifier load's archive half: {source id: archive text}, every read through this Scope (AR-03)."""
        out: dict[str, str] = {}
        for source in self._require(scope, ref)["sources"]:
            text = self._archive(scope, source["archive_ref"])
            if text is None:
                raise ArtifactNotFound(f"no archive record for source {source['id']}")
            out[source["id"]] = text
        return out

    # -- writes --------------------------------------------------------------------------------------------------

    def _plan(
        self, scope: Scope, key: str | None, parent: Mapping[str, Any] | None, size: int
    ) -> tuple[dict[str, Any] | None, int]:
        """(the version this key already made, else None; the next version number). Scan of the Scope's world."""
        docs = self._docs(f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/")
        if key is not None:
            for doc in docs:
                if doc["owner"] == scope.owner and doc["idempotency_key"] == key:
                    return doc, 0
        if sum(d["size_bytes"] for d in docs) + size > MAX_WORLD:
            raise _refuse("AR-04", "the world would hold more than 200,000,000 bytes")
        if parent is None:
            return None, 1
        have = [
            d["artifact"]["version"]
            for d in docs
            if d["owner"] == scope.owner and d["artifact"]["artifact_id"] == parent["artifact_id"]
        ]
        if parent["version"] not in have:
            raise ArtifactNotFound(f"no artifact {parent['artifact_id']} version {parent['version']}")
        return None, max(have) + 1

    def _blob_state(self, scope: Scope, doc: dict[str, Any]) -> str:
        """`ok` (exact key present and its hash matches), `missing`, or `bad`. An exact-key read, never a listing."""
        try:
            data = self._blobs.read(_blob_key(scope, doc["artifact"]))
        except FileNotFoundError:
            return "missing"
        return "ok" if self._hash(data) == doc["content_sha256"] and len(data) == doc["size_bytes"] else "bad"

    def _settle(self, scope: Scope, doc: dict[str, Any]) -> StoredVersion | None:
        """An idempotency hit whose blob is not intact. `ok`: the version. Younger than GRACE: ArtifactBusy (its writer
        may be mid-write, possibly in another process). A bad blob is corrupt, never repaired. Only a record whose
        blob is still missing after GRACE is an interrupted write: it is purged and None is returned (redo it)."""
        state = self._blob_state(scope, doc)
        if state == "ok":
            return StoredVersion(doc)
        ref = doc["artifact"]
        if self._clock() - _when(doc["created_at"]) <= GRACE:
            raise ArtifactBusy(f"artifact {ref['artifact_id']} version {ref['version']} is still being written")
        if state == "bad":
            self._verified(scope, doc)  # announces and raises ArtifactCorrupt (AR-01)
            return StoredVersion(doc)
        path = _record_path(scope, ref)
        if self._meta.get(path) == doc:  # still the record we judged
            self._purge(path)
        return None

    def _append(
        self, scope: Scope, parent: dict[str, Any] | None, data: bytes, fields: dict[str, Any]
    ) -> StoredVersion:
        """Record first, then blob: a blob always has a record that retention and erasure list. A record whose blob
        is missing (an interrupted write) reads as corrupt, is purgeable, and never blocks the next version. Nothing
        another writer may still be completing is deleted or overwritten."""
        for _ in range(_RETRIES):
            with self._lock:
                existing, version = self._plan(scope, fields["idempotency_key"], parent, len(data))
                if existing is not None:
                    settled = self._settle(scope, existing)
                    if settled is not None:
                        return settled
                    continue  # the stale record was purged: plan again
                art = parent["artifact_id"] if parent else self._new_id()
                if type(art) is not str or _ID["art"].fullmatch(art) is None:
                    raise ArtifactError("the id source returned a malformed artifact id")
                ref = {"artifact_id": art, "version": version}
                record = {
                    "v": "1.0",
                    "artifact": ref,
                    "org_id": scope.org_id,
                    "world_id": scope.world_id,
                    "owner": scope.owner,
                    "parents": [dict(parent)] if parent else [],
                    "created_at": _iso(self._clock()),
                    **fields,
                }
                if record["screened_at"] is not None and record["screened_at"] > record["created_at"]:
                    raise _refuse("AR-07", "screened_at is after created_at")
                self._check_record(record)
                stored = self._write(scope, record, data)
                if stored is not None:
                    return stored
                # another writer took this version: plan again
        raise ArtifactError("AR-02: could not take the next version")

    def _check_record(self, record: dict[str, Any]) -> None:
        try:
            self._validate_record(record)
        except Exception:  # noqa: BLE001 - any validator failure refuses the call; its text may echo values
            raise _refuse("schema", "the record does not validate") from None

    def _write(self, scope: Scope, record: dict[str, Any], data: bytes) -> StoredVersion | None:
        """Record, then blob. None when the record path is already taken (nothing written)."""
        ref = record["artifact"]
        path, key = _record_path(scope, ref), _blob_key(scope, ref)
        try:
            self._meta.create(path, record)
        except FileExistsError:
            return None
        try:
            self._blobs.create(key, data)
        except FileExistsError:
            # A blob is already at a version whose record we hold: accept it only if it is these bytes
            # (create-only fill-in); otherwise it is corrupt. Never delete or rewrite it.
            self._verified(scope, record)
        except BaseException:
            # The create may have written some or all of the bytes before it raised. Delete the blob, and the
            # record only if that worked; otherwise the record stays listed (reads as corrupt) and purgeable.
            try:
                self._blobs.delete(key)
                self._meta.delete(path)
            except Exception:  # noqa: BLE001
                pass
            raise
        return StoredVersion(record, written=True)

    def import_version(self, scope: Scope, record: dict[str, Any], content: bytes) -> StoredVersion:
        """One version from an untrusted run bundle (FR-MEM-10) under the IMPORTER's `scope`, keeping the ids,
        version, bytes, hash and times the run's events name. AR-03 identity and AR-06 `sources` are overwritten;
        AR-04 kinds and caps come before any hash; AR-01 hash and size; AR-02 gapless with one earlier parent;
        AR-05 key; AR-07 text must survive the redactor unchanged and a `clean` claim is judged again here (a restore
        takes its parent's verdict: it is an exact copy). `written` on the result says whether this call stored it."""
        _check_scope(scope)
        rec = self._check_import(scope, record, content)
        path = _record_path(scope, rec["artifact"])
        held = self._meta.get(path)
        if held is None:
            self._plan(scope, None, None, len(content))  # AR-04 world cap, before any hashing
        if self._hash(content) != rec["content_sha256"]:
            raise _refuse("AR-01", "the bytes do not match the record's hash")
        if rec["media_type"] in TEXT_TYPES and self._clean(content) is not None:
            raise _refuse("AR-07", "the text holds what the secret redactor removes; nothing stored")
        if held is None and rec["screening"] == "clean" and rec["origin"]["kind"] != "restore":
            rec["screening"], rec["screened_at"] = self._screen(content, rec["media_type"])  # never the claim
        with self._lock:
            held = held or self._meta.get(path)
            if held is None:
                self._check_lineage(scope, rec, len(content))
                stored = self._write(scope, rec, content)
                if stored is not None:
                    return stored
                held = self._meta.get(path)
        if held is None or held["owner"] != scope.owner or held["content_sha256"] != rec["content_sha256"]:
            raise _refuse("AR-02", "the version cannot be placed in this scope")  # same answer for another owner's
        if self._blob_state(scope, held) == "missing":  # never purged here: its writer may still be finishing
            raise ArtifactBusy(f"artifact {rec['artifact']['artifact_id']} is not completely stored yet")
        self._verified(scope, held)  # AR-01: a corrupt blob raises ArtifactCorrupt
        return StoredVersion(held)

    def _check_import(self, scope: Scope, record: Any, content: bytes) -> dict[str, Any]:
        """The record in the importer's scope, checked without hashing: schema, ids matched whole, kinds, caps."""
        if not isinstance(record, dict):
            raise _refuse("schema", "the record is not an object")
        rec = copy.deepcopy(record) | {
            "org_id": scope.org_id,
            "world_id": scope.world_id,
            "owner": scope.owner,
            "sources": [],
        }
        self._check_record(rec)
        try:
            for ref in (rec["artifact"], *rec["parents"]):
                _ref(ref)
            # whole-string parse: the schema's `$` lets a trailing newline through
            stamps = [_when(s) for s in (rec["created_at"], rec["screened_at"]) if s is not None]
        except ValueError:
            raise _refuse("AR-03", "an artifact ref or a time is malformed") from None
        if any(stamp > self._clock() for stamp in stamps):  # a future record would never be purged (AR-08)
            raise _refuse("AR-08", "a record time is after the store's clock")
        if (rec["screening"] == "unscreened") != (rec["screened_at"] is None):
            raise _refuse("AR-07", "screened_at is null exactly when unscreened")
        origin = rec["origin"]
        if origin["kind"] == "restore" and not rec["parents"]:
            raise _refuse("AR-02", "a restore copies an earlier version")
        kind = "upload" if origin["kind"] == "restore" else origin["kind"]  # a restore has no unit, agent or key
        self._check_new(
            NewVersion(
                media_type=rec["media_type"],
                content=content,
                run_id=rec["run_id"],
                origin=Origin(kind=kind, unit=origin["unit"], agent=origin["agent"]),
                idempotency_key=rec["idempotency_key"],
            )
        )
        if rec["size_bytes"] != len(content):
            raise _refuse("AR-01", "the size does not match the bytes")
        return rec

    def _check_lineage(self, scope: Scope, rec: dict[str, Any], size: int) -> None:
        """AR-05 key, AR-04 world cap and AR-02 order for an imported version (under the lock)."""
        world = self._docs(f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/")
        if sum(d["size_bytes"] for d in world) + size > MAX_WORLD:
            raise _refuse("AR-04", "the world would hold more than 200,000,000 bytes")
        docs = [d for d in world if d["owner"] == scope.owner]
        key, (art, version) = rec["idempotency_key"], (rec["artifact"]["artifact_id"], rec["artifact"]["version"])
        if key is not None and any(d["idempotency_key"] == key for d in docs):
            raise _refuse("AR-05", "another version holds this idempotency key")
        have = {d["artifact"]["version"] for d in docs if d["artifact"]["artifact_id"] == art}
        parents = [(p["artifact_id"], p["version"]) for p in rec["parents"]]
        continues = parents == [] if version == 1 else len(parents) == 1 and parents[0][0] == art
        if version != max(have, default=0) + 1 or not continues or any(v not in have for _, v in parents):
            raise _refuse("AR-02", "the version does not continue an earlier version of this artifact")
        if rec["origin"]["kind"] == "restore":  # an exact copy of the parent this scope holds (FR-MEM-06)
            parent = next(d for d in docs if d["artifact"] == {"artifact_id": art, "version": parents[0][1]})
            if any(parent[k] != rec[k] for k in ("content_sha256", "media_type", "size_bytes")):
                raise _refuse("AR-02", "a restore is not an exact copy of its parent")
            rec.update({k: parent[k] for k in ("screening", "screened_at", "redacted")})

    def put(self, scope: Scope, new: NewVersion) -> StoredVersion:
        _check_scope(scope)
        parent = self._check_new(new)
        size = len(new.content)  # the object's own length: caps come before any copy or hash
        existing, _ = self._plan(scope, new.idempotency_key, parent, size)
        if existing is not None and self._blob_state(scope, existing) == "ok":
            return StoredVersion(existing)  # a restarted unit gets its version back; the first bytes win (AR-05)
        fetch_digest = None
        for source in new.sources:
            try:
                found = self._archive(scope, source["archive_ref"])
            except Exception:  # noqa: BLE001
                found = None
            if found is None:
                raise _refuse("AR-03", f"source {source['id']} is not a raw-archive record of this run, org and world")
            if new.origin.kind == "fetch":
                try:
                    payload = json.loads(found)
                    source_url = payload["source"]["ref"]
                    parsed = urlsplit(source_url)
                    if (
                        payload["tool"] != "fetch_url"
                        or payload["source"]["kind"] != "web"
                        or parsed.scheme not in {"https", "http"}
                        or not parsed.hostname
                        or parsed.username
                        or parsed.password
                        or parsed.query
                        or parsed.fragment
                        or payload["media_type"] != new.media_type
                        or type(payload["size"]) is not int
                        or payload["size"] != size
                    ):
                        raise ValueError("not matching fetch metadata")
                    fetch_digest = payload["sha256"]
                except Exception:
                    raise _refuse("AR-09", "a fetch needs its own matching archived metadata") from None
        data, redacted = self._prepare(new)
        digest = self._hash(data)
        if new.origin.kind == "fetch" and fetch_digest != digest:
            raise _refuse("AR-09", "fetched bytes do not match their archived fingerprint")
        screening, screened_at = self._screen(data, new.media_type)
        if new.screening_hint == "flagged" and screening != "flagged":  # the hint only ever raises (AR-07)
            screening, screened_at = "flagged", screened_at or _iso(self._clock())
        fields = {
            "run_id": new.run_id,
            "media_type": new.media_type,
            "size_bytes": len(data),
            "content_sha256": digest,
            "origin": {"kind": new.origin.kind, "unit": new.origin.unit, "agent": new.origin.agent},
            "sources": [{"id": s["id"], "archive_ref": s["archive_ref"]} for s in new.sources],
            "screening": screening,
            "screened_at": screened_at,
            "redacted": redacted,
            "idempotency_key": new.idempotency_key,
        }
        return self._append(scope, parent, data, fields)

    def _check_new(self, new: NewVersion) -> dict[str, Any] | None:
        """Shape, kinds and caps: everything that can be refused without hashing. Returns the normalised parent."""
        origin, media = new.origin, new.media_type
        if new.screening_hint is not None and (type(new.screening_hint) is not str or new.screening_hint != "flagged"):
            raise _refuse("AR-07", "a screening hint can only be 'flagged'; the store alone says clean")
        if not isinstance(origin, Origin) or origin.kind not in ("unit", "render", "upload", "fetch"):
            raise _refuse("AR-02", "origin must be unit, render, upload or fetch (restore has its own call)")
        if type(media) is not str or media not in TEXT_TYPES | FILE_TYPES:
            raise _refuse("AR-04", "media type is not one of the nine")
        if origin.kind == "unit" and media not in TEXT_TYPES:
            raise _refuse("AR-04", "a unit's output is text or JSON, never a file")
        if origin.kind == "render" and media not in FILE_TYPES:
            raise _refuse("AR-04", "render makes only files")
        if type(new.run_id) is not str or _RUN_ID.fullmatch(new.run_id) is None:
            raise _refuse("AR-03", "run id is malformed")
        has_unit, has_agent = origin.kind in ("unit", "render", "fetch"), origin.kind in ("unit", "fetch")
        if (
            (origin.unit is not None) != has_unit
            or (has_agent and origin.agent is None)
            or (origin.agent is not None and origin.kind == "upload")
        ):
            raise _refuse("AR-02", "origin does not fit its kind")
        if (origin.unit is not None and _UNIT_ID.fullmatch(origin.unit) is None) or (
            origin.agent is not None and _AGENT_ID.fullmatch(origin.agent) is None
        ):
            raise _refuse("AR-03", "origin ids are malformed")
        key = new.idempotency_key
        if has_unit:
            pattern = _FETCH_KEY if origin.kind == "fetch" else _KEY
            match = pattern.fullmatch(key) if type(key) is str else None  # also bounds the output index to 0..9
            if match is None or match.group(1) != new.run_id or match.group(2) != origin.unit:
                raise _refuse("AR-05", "the idempotency key must be <run>:<unit>:<attempt>:<index> of this output")
        elif key is not None:
            raise _refuse("AR-05", "an upload has no idempotency key")
        if not isinstance(new.content, bytes) or len(new.content) < 1:
            raise _refuse("AR-04", "content must be at least 1 byte")
        if len(new.content) > (MAX_TEXT if media in TEXT_TYPES else MAX_FILE):
            raise _refuse("AR-04", "content is over the size cap for its kind")
        if origin.kind == "fetch":
            if media not in FILE_TYPES or len(new.sources) != 1 or self._file_sniffer is None:
                raise _refuse("AR-09", "a fetch needs a file sniffer and one archived source")
            try:
                sniffed = self._file_sniffer(new.content)
            except Exception:
                raise _refuse("AR-09", "fetched bytes are not an allowed file") from None
            if sniffed != media:
                raise _refuse("AR-09", "fetched bytes do not match their file kind")
        seen: set[str] = set()
        for source in new.sources:
            ident, ref = source.get("id"), source.get("archive_ref")
            match = _ARCHIVE_REF.fullmatch(ref) if type(ref) is str else None
            if type(ident) is not str or _SLUG.fullmatch(ident) is None or ident in seen or match is None:
                raise _refuse("AR-03", "a source id or archive ref is malformed or repeated")
            if origin.kind == "upload" or match.group(1) != new.run_id:
                raise _refuse("AR-03", "a source must be a raw-archive record of the record's own run")
            seen.add(ident)
        return None if new.parent is None else _ref(new.parent)

    def _prepare(self, new: NewVersion) -> tuple[bytes, bool]:
        """The bytes to store and whether the redactor changed them (text and JSON only; files are not read)."""
        if new.media_type not in TEXT_TYPES:
            return new.content, False
        cleaned = self._clean(new.content)
        return (new.content, False) if cleaned is None else (cleaned.encode("utf-8"), True)

    def _clean(self, content: bytes) -> str | None:
        """What the redactor makes of text or JSON bytes, or None when it changes nothing."""
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise _refuse("AR-04", "text must be UTF-8") from None
        if not text.strip():
            raise _refuse("AR-04", "text must not be whitespace only")
        try:
            cleaned = self._redact(text)
        except Exception:  # noqa: BLE001 - the error text may echo the secret
            raise _refuse("AR-07", "the secret redactor failed; nothing stored") from None
        if type(cleaned) is not str:
            raise _refuse("AR-07", "the secret redactor returned no text")
        return None if cleaned == text else cleaned

    def _screen(self, data: bytes, media_type: str) -> tuple[str, str | None]:
        """`clean`/`flagged` only from a verdict on exactly these bytes; anything else is `unscreened` (AR-07)."""
        if self._screener is None:
            return "unscreened", None
        try:
            convert = getattr(self, "_upload_text", None)
            if media_type.startswith("application/vnd.openxmlformats-officedocument.") and convert is not None:
                verdict = self._screener.check(convert(data, media_type))
            elif media_type in TEXT_TYPES:
                verdict = self._screener.check(data.decode("utf-8"))
            else:
                verdict = self._screener.check("", content=data, mime_type=media_type)
        except Exception:  # noqa: BLE001 - provider error, timeout, unsupported type: no verdict
            return "unscreened", None
        if not isinstance(verdict, dict) or type(verdict.get("flagged")) is not bool:
            return "unscreened", None
        return ("flagged" if verdict["flagged"] else "clean"), _iso(self._clock())

    def restore(self, scope: Scope, ref: Mapping[str, Any], *, by: Origin) -> StoredVersion:
        """A new version that is an exact copy of `ref` (FR-MEM-06). Not redacted or screened again."""
        doc = self._require(scope, ref)
        if not isinstance(by, Origin) or (by.kind, by.unit, by.agent) != ("restore", None, None):
            raise _refuse("AR-02", "a restore is made by Origin(kind='restore')")
        self._plan(scope, None, _ref(doc["artifact"]), doc["size_bytes"])  # the world cap, before any hashing
        data = self._verified(scope, doc)
        copied = {k: copy.deepcopy(doc[k]) for k in _RESTORE_COPIED}
        fields = {**copied, "origin": {"kind": "restore", "unit": None, "agent": None}, "idempotency_key": None}
        return self._append(scope, _ref(doc["artifact"]), data, fields)

    # -- manifests -----------------------------------------------------------------------------------------------

    def add_manifest(
        self, scope: Scope, ref: Mapping[str, Any], manifest: dict[str, Any], *, stage: str, cause: str | None
    ) -> int:
        doc = self._require(scope, ref)
        if type(stage) is not str or stage not in STAGES:
            raise _refuse("AR-06", "stage is not created, reviewed, sent or exported")
        if cause is not None and (type(cause) is not str or _ULID.fullmatch(cause) is None):
            raise _refuse("AR-06", "cause is not a ULID")
        revision: dict[str, Any] = {"n": 1, "stage": stage, "cause": cause, "manifest": copy.deepcopy(manifest)}
        validate_revision(revision)
        self._check_manifest(doc, revision["manifest"])
        prefix = _record_path(scope, doc["artifact"]) + "/manifests/"
        with self._lock:
            if self._require(scope, ref)["content_sha256"] != doc["content_sha256"]:  # re-read: still there, unchanged
                raise _refuse("AR-06", "the version changed")
            revision["n"] = len(self._meta.paths(prefix)) + 1  # append-only, no gaps
            validate_revision(revision)
            self._meta.create(f"{prefix}{revision['n']:04d}", revision)
        return revision["n"]

    def _check_manifest(self, doc: dict[str, Any], manifest: dict[str, Any]) -> None:
        """AR-06 with MF-01, MF-02, MF-03 (the schema's closed shapes) and MF-06. MF-04 and MF-05 are the caller's."""
        ref = doc["artifact"]
        if {k: manifest["artifact"].get(k) for k in ("artifact_id", "version")} != {
            "artifact_id": ref["artifact_id"],
            "version": ref["version"],
        }:
            raise _refuse("AR-06", "the manifest names another version")
        if manifest["content_sha256"] != doc["content_sha256"]:
            raise _refuse("MF-02", "the manifest carries another content hash")
        source_ids = [s["id"] for s in manifest["sources"]]
        claim_ids = [c["id"] for c in manifest["claims"]]
        if len(set(source_ids)) != len(source_ids) or len(set(claim_ids)) != len(claim_ids):
            raise _refuse("MF-01", "source or claim ids repeat")
        if any(not set(c["source_ids"]) <= set(source_ids) for c in manifest["claims"]):
            raise _refuse("MF-01", "a claim names a source that is not in the manifest")
        if not {s["id"] for s in doc["sources"]} <= set(source_ids):
            raise _refuse("AR-06", "a record source is not a source of the manifest")
        parents = {(p["artifact_id"], p["version"]) for p in manifest["parents"]}
        if any(a != ref["artifact_id"] or v >= ref["version"] for a, v in parents):
            raise _refuse("MF-02", "parents must be earlier versions of the same artifact")
        if (
            doc["origin"]["kind"] == "restore"
            and (
                doc["parents"][0]["artifact_id"],
                doc["parents"][0]["version"],
            )
            not in parents
        ):
            raise _refuse("MF-02", "a restore's manifest names the version it restores")
        for text in _strings(manifest):  # MF-06, fail closed
            try:
                changed = self._redact(text) != text
            except Exception:  # noqa: BLE001
                changed = True
            if changed:
                raise _refuse("MF-06", "the manifest holds what the secret redactor removes")

    def manifest_revisions(self, scope: Scope, ref: Mapping[str, Any]) -> list[dict[str, Any]]:
        doc = self._require(scope, ref)
        prefix = _record_path(scope, doc["artifact"]) + "/manifests/"
        revisions = [self._meta.get(p) for p in self._meta.paths(prefix)]
        found = [r for r in revisions if r is not None]
        if not found:
            raise ArtifactNotFound(f"no manifest for artifact {ref['artifact_id']} version {ref['version']}")
        return sorted(found, key=lambda r: r["n"])

    def manifest(self, scope: Scope, ref: Mapping[str, Any]) -> dict[str, Any]:
        return self.manifest_revisions(scope, ref)[-1]["manifest"]

    def _purge(self, record_id: str) -> None:
        """Remove one version: every blob generation, its manifest revisions, then its record (last, so a crash
        leaves it listed for the next purge)."""
        match = _RECORD_PATH.fullmatch(record_id)
        assert match is not None
        org, world, art, version = match.groups()
        with self._lock:
            self._blobs.delete(f"orgs/{org}/worlds/{world}/artifacts/{art}/v{version}")
            for path in self._meta.paths(record_id + "/manifests/"):
                self._meta.delete(path)
            self._meta.delete(record_id)

    def retention(self) -> _Retention:
        return _Retention(self)


_RESTORE_COPIED = (
    "run_id",
    "media_type",
    "size_bytes",
    "content_sha256",
    "sources",
    "screening",
    "screened_at",
    "redacted",
)


# --- FR-MEM-09 retention adapter (registered as `gcs_artifacts`) ---------------------------------------------------


@dataclass(frozen=True)
class _Record:
    entity: str
    record_id: str  # the version's record path: built from validated ids only
    created_at: datetime
    user_id: str | None


class _Retention:
    """One retention record per stored version (entity `artifact`, 90 days); never carries content."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def records(self) -> list[_Record]:
        meta, out = self._store._meta, []
        for path in meta.paths("orgs/"):
            doc = meta.get(path) if _RECORD_PATH.fullmatch(path) else None
            if doc is not None:
                out.append(_Record("artifact", path, _when(doc["created_at"]), doc["owner"]))
        return out

    def delete(self, record_id: str) -> None:
        """Idempotent. Removes every blob generation, the manifest revisions and the record (record last, so a
        crash leaves it listed for the next purge)."""
        if type(record_id) is not str or _RECORD_PATH.fullmatch(record_id) is None:
            return
        self._store._purge(record_id)
