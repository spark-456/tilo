"""Helpers for the FR-MEM-06 artifact store acceptance tests (ADR-0018, contracts/artifact.rules.md AR-01..AR-08).

Named `_artifact_testlib` because this directory has no `__init__.py`: pytest's "prepend" import mode makes every
helper module name global for the whole session. The public API these helpers and tests assume is pinned in
`API_FR_MEM_06.md` (the builder may override it, updating the tests in the same PR). Everything here is a fake: no
network, an injected clock, in-memory or tmp_path backends, a recording proxy around the backends.

`tilo_memory.artifacts` does not exist yet, so every test module fails at collection with `ModuleNotFoundError: No
module named 'tilo_memory.artifacts'`. That is the right failure."""

from __future__ import annotations

import functools
import hashlib
import json
import pathlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_memory.artifacts import (
    ArtifactStore,
    LocalDirBlobBackend,
    MemoryBlobBackend,
    MemoryMetaBackend,
    NewVersion,
    Origin,
    Scope,
    StoredVersion,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"

T0 = datetime(2026, 10, 5, 9, 30, 0, tzinfo=UTC)
ORG, WORLD, OWNER, RUN = "org_acme", "w_alpha", "u_alice", "r_run1"
OTHER_ORG, OTHER_WORLD, OTHER_OWNER = "org_other", "w_beta", "u_bob"
ARTICLE = b"# Market brief\n\nThe supplier price table is attached.\n"
JSON_DOC = b'{"rows": [1, 2, 3]}'

MB = 1_000_000
MAX_TEXT = 2 * MB  # BQ-257
MAX_FILE = 50 * MB
MAX_WORLD = 200 * MB

TEXT_TYPES = ("text/markdown", "text/csv", "application/json")
FILE_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png",
    "image/jpeg",
)
ALL_TYPES = TEXT_TYPES + FILE_TYPES
SAMPLE = {
    "text/markdown": ARTICLE,
    "text/csv": b"item,price\nbolt,4\n",
    "application/json": JSON_DOC,
}
for _t in FILE_TYPES:
    SAMPLE[_t] = b"%file-bytes% " + _t.encode("ascii")

# A fake secret assembled at runtime (CLAUDE.md: no secret-looking literals in the repo).
SECRET = "fake-secret-" + "".join(["0x", "DEAD", "BEEF"])


def iso(moment: datetime) -> str:
    """The contract's timestamp: UTC, exactly three fractional digits."""
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def sha(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


# --- JSON Schema validation (the store must do this itself; the tests do it independently) --------


@functools.cache
def build_registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data.get("$id") or path.resolve().as_uri(), Resource.from_contents(data, DRAFT202012)))
    return Registry().with_resources(resources)


@functools.cache
def _validator(schema_file: str, fragment: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((CONTRACTS / schema_file).read_text(encoding="utf-8"))
    if fragment:
        schema = {"$ref": f"{schema['$id']}{fragment}"}
    return jsonschema.Draft202012Validator(schema, registry=build_registry())


def schema_errors(instance: Any, schema_file: str, fragment: str = "") -> list[str]:
    validator = _validator(schema_file, fragment)
    return [e.message for e in validator.iter_errors(instance)]


# --- time, hashing, screening, redaction, archive: the injected collaborators ---------------------


class Clock:
    """The store's only source of time. `tick` makes every read later than the last (`screened_at <= created_at`)."""

    def __init__(self, start: datetime = T0, tick: timedelta = timedelta(0)) -> None:
        self.now = start
        self.tick = tick
        self.reads: list[datetime] = []

    def __call__(self) -> datetime:
        value = self.now
        self.reads.append(value)
        self.now = self.now + self.tick
        return value

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


class Hasher:
    """Counts every hash the store takes. Caps and kinds must be checked before the first call."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, data: bytes) -> str:
        self.calls += 1
        return hashlib.sha256(data).hexdigest()


class FakeSafety:
    """SafetyProvider-like screener (`check` -> {"flagged", "reason"}); records exactly what it was shown."""

    def __init__(self, *, flagged: bool = False, error: BaseException | None = None, result: Any = ...) -> None:
        self.flagged = flagged
        self.error = error
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> Any:
        self.calls.append({"text": text, "content": content, "mime_type": mime_type})
        if self.error is not None:
            raise self.error
        if self.result is not ...:
            return self.result
        return {"flagged": self.flagged, "reason": "fake" if self.flagged else None}


class Redactor:
    """The secret redactor: replaces SECRET. Counts and records its inputs; may be told to raise."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return text.replace(SECRET, "[REDACTED]")


class FakeArchive:
    """Raw-archive lookup keyed by (org, world, archive_ref). Records the Scope of every read."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str, str], str] = {}
        self.calls: list[tuple[Scope, str]] = []

    def add(self, scope: Scope, archive_ref: str, text: str | None = None) -> None:
        self.records[(scope.org_id, scope.world_id, archive_ref)] = text or f"archive text of {archive_ref}"

    def remove(self, scope: Scope, archive_ref: str) -> None:
        self.records.pop((scope.org_id, scope.world_id, archive_ref), None)

    def __call__(self, scope: Scope, archive_ref: str) -> str | None:
        self.calls.append((scope, archive_ref))
        return self.records.get((scope.org_id, scope.world_id, archive_ref))


# --- backends -------------------------------------------------------------------------------------


class Recording:
    """Forwards every attribute of `inner` and records each method call as (name, args, kwargs)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return attr(*args, **kwargs)

        return call

    def called(self, name: str) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
        return [c for c in self.calls if c[0] == name]

    def mentions(self, needle: str) -> bool:
        return needle in repr(self.calls)


class SizeOnlyBlobs:
    """A BlobBackend that keeps the object it is given, so a `Sized` fake needs no real memory."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def create(self, key: str, data: bytes) -> None:
        with self._lock:
            if key in self.objects:
                raise FileExistsError(key)
            self.objects[key] = data

    def read(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise FileNotFoundError(key) from None

    def delete(self, key: str) -> None:
        with self._lock:
            self.objects.pop(key, None)

    def keys(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


class Sized(bytes):
    """A few real bytes that report `len()` of `size`: for the caps, without allocating 200 MB."""

    _size: int

    def __new__(cls, size: int, seed: bytes = b"x") -> Sized:
        obj = super().__new__(cls, seed)
        obj._size = size
        return obj

    def __len__(self) -> int:
        return self._size


# --- the rig --------------------------------------------------------------------------------------


def scope_of(org: str = ORG, world: str = WORLD, owner: str = OWNER) -> Scope:
    return Scope(org_id=org, world_id=world, owner=owner)


def blob_key(scope: Scope, ref: dict[str, Any]) -> str:
    return f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{ref['artifact_id']}/v{ref['version']:06d}"


def record_path(scope: Scope, ref: dict[str, Any]) -> str:
    base = f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{ref['artifact_id']}"
    return f"{base}/versions/{ref['version']:06d}"


def revision_path(scope: Scope, ref: dict[str, Any], n: int) -> str:
    return f"{record_path(scope, ref)}/manifests/{n:04d}"


@dataclass
class Rig:
    store: ArtifactStore
    meta: Recording
    blobs: Recording
    clock: Clock
    hasher: Hasher
    safety: FakeSafety | None
    redactor: Redactor
    archive: FakeArchive
    alerts: list[dict[str, Any]]
    scope: Scope
    kind: str
    root: pathlib.Path | None = None
    _attempts: int = field(default=0, repr=False)

    def next_attempt(self) -> int:
        self._attempts += 1
        return self._attempts

    def new(
        self,
        content: bytes = ARTICLE,
        *,
        media_type: str = "text/markdown",
        run: str = RUN,
        unit: str = "U1",
        agent: str | None = "A_s1",
        index: int = 0,
        attempt: int | None = None,
        key: str | None = "auto",
        parent: dict[str, Any] | None = None,
        sources: tuple[dict[str, str], ...] = (),
        kind: str = "unit",
    ) -> NewVersion:
        attempt = self.next_attempt() if attempt is None else attempt
        if key == "auto":
            key = f"{run}:{unit}:{attempt}:{index}"
        return NewVersion(
            media_type=media_type,
            content=content,
            run_id=run,
            origin=Origin(kind=kind, unit=unit, agent=agent),
            sources=sources,
            idempotency_key=key,
            parent=parent,
        )

    def put(self, content: bytes = ARTICLE, *, scope: Scope | None = None, **kw: Any) -> StoredVersion:
        return self.store.put(scope or self.scope, self.new(content, **kw))

    def upload(
        self, content: bytes = ARTICLE, media_type: str = "text/markdown", *, scope: Scope | None = None
    ) -> StoredVersion:
        new = NewVersion(
            media_type=media_type, content=content, run_id=RUN, origin=Origin(kind="upload"), idempotency_key=None
        )
        return self.store.put(scope or self.scope, new)

    def render(self, content: bytes, media_type: str, *, unit: str = "U3", **kw: Any) -> StoredVersion:
        return self.put(content, media_type=media_type, unit=unit, agent=None, kind="render", **kw)

    def restore(self, ref: dict[str, Any], *, scope: Scope | None = None) -> StoredVersion:
        return self.store.restore(scope or self.scope, ref, by=Origin(kind="restore"))

    def tamper(self, stored: StoredVersion, data: bytes, *, scope: Scope | None = None) -> None:
        key = blob_key(scope or self.scope, stored.ref)
        self.blobs.inner.delete(key)
        self.blobs.inner.create(key, data)


def make_rig(
    kind: str,
    tmp_path: pathlib.Path | None,
    *,
    safety: Any = "default",
    redactor: Redactor | None = None,
    clock: Clock | None = None,
    blobs: Any = None,
    meta: Any = None,
    scope: Scope | None = None,
    **store_kwargs: Any,
) -> Rig:
    """One ArtifactStore on the `memory` or `local` (tmp_path) blob backend, or on `blobs` (kind `custom`)."""
    root = None
    if blobs is None:
        if kind == "local":
            assert tmp_path is not None
            root = tmp_path / "artifacts"
            blobs = LocalDirBlobBackend(root)
        else:
            blobs = MemoryBlobBackend()
    rec_meta, rec_blobs = Recording(meta or MemoryMetaBackend()), Recording(blobs)
    screener = FakeSafety() if safety == "default" else safety
    clk, hasher, red, archive, alerts = clock or Clock(), Hasher(), redactor or Redactor(), FakeArchive(), []
    store = ArtifactStore(
        rec_meta,
        rec_blobs,
        clock=clk,
        redactor=red,
        archive_lookup=archive,
        alert_sink=alerts.append,
        screener=screener,
        hasher=hasher,
        **store_kwargs,
    )
    return Rig(store, rec_meta, rec_blobs, clk, hasher, screener, red, archive, alerts, scope or scope_of(), kind, root)


def outcome(fn: Callable[[], Any]) -> tuple[Any, ...]:
    """What a call did, comparable between two stores: its value, or the exception type and message."""
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - the point is to compare every kind of failure
        return ("raised", type(exc), str(exc))
    return ("returned", value)


# --- manifests ------------------------------------------------------------------------------------


def make_manifest(stored: StoredVersion, *, content: bytes | None = None, **overrides: Any) -> dict[str, Any]:
    """A schema-valid Manifest for `stored`: names the version and its hash, one web source per record source."""
    record = stored.record
    manifest: dict[str, Any] = {
        "v": "1.0",
        "artifact": stored.ref,
        "content_sha256": record["content_sha256"] if content is None else sha(content),
        "parents": list(record["parents"]),
        "produced_by": {"agent_id": "A_s1", "role": "specialist", "skill": None, "model_role": None, "profile": None},
        "inputs": [],
        "sources": [
            {
                "id": s["id"],
                "kind": "web",
                "ref": f"https://example.com/{s['id']}",
                "fingerprint": "sha256:" + "ab" * 32,
                "fetched_at": "2026-10-05T09:00:00.000Z",
            }
            for s in record["sources"]
        ],
        "claims": [],
        "events": [],
        "authz": None,
    }
    manifest.update(overrides)
    return manifest


ULID_A = "01JB5VQ0000000000000000204"
ULID_B = "01JB5VQ0000000000000000205"
