"""Durable stores for a run's artifacts and raw archive (PROD-WIRE 2b; ADR-0018 T8, FR-MEM-04; ADR-0023 / ADR-0026).

`tilo_memory` and `tilo_archive` stay pure, so the adapters live here and take duck-typed clients. Artifact records go
to Firestore (the document path IS the store path), artifact bytes to the versioned `artifacts` GCS bucket, and the raw
archive to the CMEK `archive` bucket, one create-only object per line. Every write is create-only, and a refused
create over identical bytes is our own write whose answer was lost (the client libraries retry). The doors open a
store only for an explicit switch (never implied by `K_SERVICE`), with application default credentials only. Nothing
here does I/O or builds a client at import.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from google.api_core import exceptions as gexc
from tilo_archive import RunArchive
from tilo_archive.archive import ORG_ID_RE, RUN_ID_RE
from tilo_memory.artifacts import ArtifactStore

logger = logging.getLogger(__name__)

_SEGMENT = re.compile(r"[0-9A-Za-z_]+")
_PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]")
_ADDRESS = re.compile(r"[0-9]+(\.[0-9]+){3}")
_OBJECT = re.compile(r"[0-9]{8}\.jsonl")
_MAX_SEQ = 99_999_999  # the 8 digits of an archive object name
_ATTEMPTS = 100
_LOCK_WAIT = (gexc.Aborted, gexc.Conflict)  # `AlreadyExists` is a Conflict too: caught first, never retried
_EMULATOR_HOSTS = ("FIRESTORE_EMULATOR_HOST", "STORAGE_EMULATOR_HOST")
_BUCKETS = ("TILO_ARTIFACTS_BUCKET", "TILO_ARCHIVE_BUCKET")


class RunStoreNotConfigured(NotImplementedError):
    """A door was not given an explicit switch, a bucket and a valid project (no client was built)."""


class RunStoreUnavailable(RunStoreNotConfigured):
    """The config was valid but a client could not be built (no credentials, no network): 503 `store_unavailable`.
    Still a `RunStoreNotConfigured`, so every caller that refuses on one refuses on this too."""


def _create_or_same(blob: Any, data: bytes, content_type: str) -> bool:
    """A create-only upload; True when the object now holds exactly `data`. google-cloud-storage retries a
    generation-matched upload, so a first attempt that landed but lost its answer comes back as 412: identical bytes
    are that write of ours, other bytes (or none) another writer's."""
    try:
        blob.upload_from_string(data, content_type=content_type, if_generation_match=0)
        return True
    except gexc.PreconditionFailed:
        pass
    try:
        return bytes(blob.download_as_bytes()) == data
    except gexc.NotFound:  # removed since: not ours either
        return False


def _record_seq(line: str) -> int | None:
    """The `seq` a record line (a JSON object with `seq` or `prev_hash`) names its object by; None for any other
    JSON line. A record without a usable seq, or a line that is not JSON, is refused (nothing is written)."""
    try:
        parsed = json.loads(line)
    except (ValueError, RecursionError):
        raise ValueError("an archive line must be JSON") from None
    if not isinstance(parsed, dict) or not {"seq", "prev_hash"} & parsed.keys():
        return None
    seq = parsed.get("seq")
    if type(seq) is not int or not 1 <= seq <= _MAX_SEQ:
        raise ValueError(f"a record line needs an integer seq from 1 to {_MAX_SEQ}")
    return seq


def _segment(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _SEGMENT.fullmatch(value) is not None
        and not (
            value.startswith("__") and value.endswith("__")  # Firestore reserves `__name__` ids
        )
    )


def _safe_key(key: Any) -> str:
    if not isinstance(key, str) or not all(_segment(part) for part in key.split("/")):
        raise ValueError("unsafe object key")
    return key


class FirestoreMetaBackend:
    """A `MetaBackend` on Firestore: the document at `path` holds `{"v": 1, "doc": <the record as a JSON string>}`
    (Firestore refuses arrays of arrays). `paths` walks `list_documents` and sub-collections, so it needs no index."""

    def __init__(self, client: Any, *, collection_root: str) -> None:
        if not _segment(collection_root):
            raise ValueError("unsafe collection root")
        self._client, self._root = client, collection_root

    def _ref(self, path: Any) -> Any:
        parts = path.split("/") if isinstance(path, str) else []
        if len(parts) % 2 or parts[:1] != [self._root] or not all(_segment(p) for p in parts):
            raise ValueError("a document path inside the root is required")
        return self._client.document(path)

    def create(self, path: str, doc: dict[str, Any]) -> None:
        ref, body = self._ref(path), {"v": 1, "doc": json.dumps(doc, sort_keys=True, ensure_ascii=False)}
        for attempt in range(_ATTEMPTS):
            try:
                ref.create(body)
            except gexc.AlreadyExists:  # on attempt 0 too: the client's own retry may be what met our first write
                if (snapshot := ref.get()).exists and snapshot.to_dict() == body:
                    return  # our own create landed before a lost answer
                raise FileExistsError(path) from None
            except _LOCK_WAIT:  # the emulator's "409 Transaction lock timeout" (Aborted): try again, bounded
                time.sleep(random.uniform(0, 0.02 * 2 ** min(attempt, 4)))
                continue
            return
        raise RuntimeError("the artifact store is busy")

    def get(self, path: str) -> dict[str, Any] | None:
        snapshot = self._ref(path).get()
        if not snapshot.exists:
            return None
        found: dict[str, Any] = json.loads(snapshot.to_dict()["doc"])
        return found

    def delete(self, path: str) -> None:
        self._ref(path).delete()  # no precondition: deleting a missing document is not an error

    def paths(self, prefix: str = "") -> list[str]:
        *head, last = prefix.split("/")
        if head:
            ok = head[0] == self._root and all(_segment(p) for p in head) and (last == "" or _segment(last))
        else:
            ok = self._root.startswith(last)
        if not ok:
            raise ValueError("a prefix inside the root is required")
        found: list[str] = []
        if len(head) % 2 == 1:  # the deepest whole segment names a collection
            self._walk(self._client.collection("/".join(head)), found)
        elif head:  # ... a document: only its sub-collections are under the prefix
            for sub in self._client.document("/".join(head)).collections():
                self._walk(sub, found)
        else:
            self._walk(self._client.collection(self._root), found)
        return sorted(p for p in found if p.startswith(prefix))

    def _walk(self, collection: Any, found: list[str]) -> None:
        live = {snap.reference.path for snap in collection.select([]).stream()}  # existing documents only
        for ref in collection.list_documents():  # also the missing parents that hold sub-collections
            if ref.path in live:
                found.append(ref.path)
            for sub in ref.collections():
                self._walk(sub, found)


class GcsBlobBackend:
    """A `BlobBackend` on a GCS bucket (`bucket(name)` builds a handle without I/O). The object name is the key."""

    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket

    def create(self, key: str, data: bytes) -> None:
        if not _create_or_same(self._bucket.blob(_safe_key(key)), bytes(data), "application/octet-stream"):
            raise FileExistsError(key)

    def read(self, key: str) -> bytes:
        try:
            return bytes(self._bucket.blob(_safe_key(key)).download_as_bytes())
        except gexc.NotFound:
            raise FileNotFoundError(key) from None

    def delete(self, key: str) -> None:
        """Every generation of exactly this key, live and noncurrent (FR-MEM-09)."""
        for blob in list(self._bucket.list_blobs(prefix=_safe_key(key), versions=True)):
            if blob.name == key:
                try:
                    self._bucket.delete_blob(key, generation=blob.generation)
                except gexc.NotFound:
                    pass

    def keys(self, prefix: str = "") -> list[str]:
        return sorted(blob.name for blob in self._bucket.list_blobs(prefix=prefix or None))


class GcsArchiveStore:
    """A `tilo_archive.archive.Store`: line `n` of a run is the create-only object `{org}/{run}/{n:08d}.jsonl`.

    A record line goes to the index of its own `seq`. Its prev_hash is the hash of the record before it as its writer
    read it, so a second writer of that seq (another instance, a stale head) is refused with `FileExistsError` and the
    caller reopens: a record never lands with a stale prev_hash (FR-MEM-04, BQ-MEM10-2). Only a line that is not a
    record moves on to the next free index after a lost race."""

    def __init__(self, bucket: Any) -> None:
        self._bucket, self._lock = bucket, threading.Lock()
        self._next: dict[tuple[str, str], int] = {}  # (org, run) -> the next index to try

    @staticmethod
    def _prefix(org_id: Any, run_id: Any) -> str:
        if not (isinstance(org_id, str) and isinstance(run_id, str)):
            raise ValueError("invalid org_id or run_id")
        if not (ORG_ID_RE.fullmatch(org_id) and RUN_ID_RE.fullmatch(run_id)):
            raise ValueError("invalid org_id or run_id")
        return f"{org_id}/{run_id}/"

    def _objects(self, prefix: str) -> list[tuple[int, Any]]:
        found = [(b.name[len(prefix) :], b) for b in self._bucket.list_blobs(prefix=prefix)]
        return sorted((int(n[:8]), b) for n, b in found if _OBJECT.fullmatch(n))

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        prefix, data = self._prefix(org_id, run_id), (line + "\n").encode("utf-8")
        seq = _record_seq(line)
        if seq is not None:
            name = f"{prefix}{seq:08d}.jsonl"
            if not _create_or_same(self._bucket.blob(name), data, "application/x-ndjson"):
                raise FileExistsError(name)  # another writer holds this seq: reopen at the head, never move on
            with self._lock:
                self._next[(org_id, run_id)] = max(self._next.get((org_id, run_id), 0), seq + 1)
            return
        for _ in range(_ATTEMPTS):
            with self._lock:
                index = self._next.get((org_id, run_id))
            if index is None:
                index = max((n for n, _ in self._objects(prefix)), default=0) + 1
            if not _create_or_same(self._bucket.blob(f"{prefix}{index:08d}.jsonl"), data, "application/x-ndjson"):
                with self._lock:  # another writer took this index: look again
                    self._next.pop((org_id, run_id), None)
                continue
            with self._lock:
                self._next[(org_id, run_id)] = index + 1
            return
        raise RuntimeError("the archive append kept losing the race; nothing was lost")

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        lines = []
        for _, blob in self._objects(self._prefix(org_id, run_id)):
            text = blob.download_as_bytes().decode("utf-8")
            lines.append(text[:-1] if text.endswith("\n") else text)
        return lines


def redact_leaves(str_redactor: Callable[[str], str]) -> Callable[[Any], Any]:
    """A payload redactor for `RunArchive` from a string redactor: every string leaf and key is masked; an error from
    `str_redactor` propagates, so the archive writes nothing (fail closed). Two keys that redact to one key are an
    error too: one value would silently replace the other."""

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            return str_redactor(value)
        if isinstance(value, Mapping):
            out: dict[Any, Any] = {}
            for k, v in value.items():
                key = redact(k) if isinstance(k, str) else k
                if key in out:
                    raise ValueError("two keys of the payload redact to the same key; nothing is archived")
                out[key] = redact(v)
            return out
        if isinstance(value, list | tuple):
            return [redact(v) for v in value]
        return value

    return redact


# --- the doors ---------------------------------------------------------------------------------------------------


def _default_firestore(project: str) -> Any:
    from tilo_api.prod import firestore_client  # noqa: PLC0415

    return firestore_client(project)


def _default_storage(project: str) -> Any:
    from google.cloud.storage import Client  # noqa: PLC0415 - imported only when a door builds its client

    return Client(project=project)


def _settings(
    env: Mapping[str, str] | None, switch: str, bucket_var: str, needs: Sequence[str], defaults: Sequence[str]
) -> tuple[str, str]:
    """(project, bucket) for a door, or `RunStoreNotConfigured`, before any client exists (the rules of the api store
    door, PROD-WIRE 1a). On Cloud Run (`K_SERVICE` present) no emulator host may be set, in `env` or the process.
    Outside it, injected factory or not, a door opens only the emulators it `needs` on a `demo-` project. The default
    factories' clients read the emulator hosts in `defaults` from `os.environ`, so a passed `env` must name the same."""
    source = os.environ if env is None else env
    project, bucket = source.get("TILO_FIRESTORE_PROJECT", ""), source.get(bucket_var, "")
    if (
        source.get(switch) != "gcs"
        or _PROJECT.fullmatch(project) is None
        or _BUCKET.fullmatch(bucket) is None
        or ".." in bucket
        or bucket.startswith("goog")
        or "google" in bucket
        or _ADDRESS.fullmatch(bucket)
    ):
        raise RunStoreNotConfigured(f"set {switch}=gcs, {bucket_var} and a valid TILO_FIRESTORE_PROJECT")
    if any(source.get(name) == bucket for name in _BUCKETS if name != bucket_var):
        raise RunStoreNotConfigured(f"{switch}: TILO_ARCHIVE_BUCKET and TILO_ARTIFACTS_BUCKET must be two buckets")
    if "API_ENDPOINT_OVERRIDE" in source or "API_ENDPOINT_OVERRIDE" in os.environ:
        raise RunStoreNotConfigured(f"{switch}: API_ENDPOINT_OVERRIDE is set (it would move the storage endpoint)")
    if "GOOGLE_CLOUD_PROJECT" in source and source["GOOGLE_CLOUD_PROJECT"] != project:
        raise RunStoreNotConfigured(f"{switch}: TILO_FIRESTORE_PROJECT must equal GOOGLE_CLOUD_PROJECT")
    if "K_SERVICE" in source or "K_SERVICE" in os.environ:
        for host in _EMULATOR_HOSTS:
            if host in source or host in os.environ:  # a deployed process never talks to an emulator host
                raise RunStoreNotConfigured(f"{switch}: {host} is set on Cloud Run")
    if not source.get("K_SERVICE") and not (project.startswith("demo-") and all(source.get(h) for h in needs)):
        raise RunStoreNotConfigured(f"outside Cloud Run {switch} opens only an emulator on a demo- project")
    if env is not None and any(os.environ.get(h, "") != env.get(h, "") for h in defaults):
        raise RunStoreNotConfigured(f"{switch}: the client reads os.environ, which names other emulator hosts than env")
    return project, bucket


def _unavailable(switch: str, exc: Exception) -> RunStoreUnavailable:
    logger.warning("%s: the store client is unavailable (%s)", switch, type(exc).__name__)  # never the text
    return RunStoreUnavailable(f"{switch}: the store client could not be built")


def open_artifact_store(
    env: Mapping[str, str] | None = None,
    *,
    firestore_client_factory: Callable[[str], Any] | None = None,
    storage_client_factory: Callable[[str], Any] | None = None,
    redactor: Callable[[str], str],
    clock: Callable[[], datetime] | None = None,
    archive_lookup: Callable[[Any, str], str | None] | None = None,
    alert_sink: Callable[[dict[str, Any]], None] | None = None,
    screener: Any | None = None,
    file_sniffer: Callable[[bytes], str] | None = None,
) -> ArtifactStore:
    """Records in Firestore, bytes in GCS: `TILO_ARTIFACTS_STORE=gcs`, `TILO_ARTIFACTS_BUCKET`, a project, under the
    rules of `_settings`. A client that cannot be built is `RunStoreUnavailable`."""
    defaults = [h for h, f in zip(_EMULATOR_HOSTS, (firestore_client_factory, storage_client_factory)) if f is None]
    switch = "TILO_ARTIFACTS_STORE"
    project, bucket = _settings(env, switch, "TILO_ARTIFACTS_BUCKET", _EMULATOR_HOSTS, defaults)
    try:
        fs_client = (firestore_client_factory or _default_firestore)(project)
        blobs = GcsBlobBackend((storage_client_factory or _default_storage)(project).bucket(bucket))
    except Exception as exc:  # noqa: BLE001 - no credentials, no network: closed, and only the type is logged
        raise _unavailable(switch, exc) from None

    def alert(payload: dict[str, Any]) -> None:
        logger.warning("artifact alert: %s", payload.get("summary", "raised"))  # ids only, never content

    return ArtifactStore(
        FirestoreMetaBackend(fs_client, collection_root="orgs"),
        blobs,
        clock=clock or (lambda: datetime.now(UTC)),
        redactor=redactor,
        archive_lookup=archive_lookup or (lambda scope, ref: None),
        alert_sink=alert_sink or alert,
        screener=screener,
        file_sniffer=file_sniffer,
    )


def open_run_archive(
    env: Mapping[str, str] | None = None,
    *,
    storage_client_factory: Callable[[str], Any] | None = None,
    redactor: Callable[[Any], Any],
) -> Callable[..., RunArchive]:
    """`open_archive(*, org_id, run_id) -> RunArchive` over the `archive` bucket: `TILO_ARCHIVE_STORE=gcs`,
    `TILO_ARCHIVE_BUCKET`, `TILO_FIRESTORE_PROJECT` (the one project id both stores share), under `_settings`."""
    hosts, switch = ("STORAGE_EMULATOR_HOST",), "TILO_ARCHIVE_STORE"
    project, bucket = _settings(
        env, switch, "TILO_ARCHIVE_BUCKET", hosts, hosts if storage_client_factory is None else ()
    )
    try:
        store = GcsArchiveStore((storage_client_factory or _default_storage)(project).bucket(bucket))
    except Exception as exc:  # noqa: BLE001
        raise _unavailable(switch, exc) from None

    def open_archive(*, org_id: str, run_id: str) -> RunArchive:
        return RunArchive(store, org_id=org_id, run_id=run_id, redactor=redactor)

    return open_archive
