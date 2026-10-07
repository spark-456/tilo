"""Durable stores for a run's artifacts and raw archive (PROD-WIRE 2b; ADR-0018 T8, FR-MEM-04; ADR-0023 / ADR-0026).

`tilo_memory` and `tilo_archive` stay pure, so the adapters live here and take duck-typed clients. Artifact records go
to Firestore (the document path IS the store path), artifact bytes to the versioned `artifacts` GCS bucket, and the raw
archive to the CMEK `archive` bucket, one create-only object per line. Every write is create-only. The doors open a
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
from google.cloud import firestore
from tilo_archive import RunArchive
from tilo_archive.archive import ORG_ID_RE, RUN_ID_RE
from tilo_memory.artifacts import ArtifactStore

logger = logging.getLogger(__name__)

_SEGMENT = re.compile(r"[0-9A-Za-z_]+")
_PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_BUCKET = re.compile(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]")
_ADDRESS = re.compile(r"[0-9]+(\.[0-9]+){3}")
_OBJECT = re.compile(r"[0-9]{8}\.jsonl")
_ATTEMPTS = 100
_LOCK_WAIT = (gexc.Aborted, gexc.Conflict)  # `AlreadyExists` is a Conflict too: caught first, never retried


class RunStoreNotConfigured(NotImplementedError):
    """A door was not given an explicit switch, a bucket and a valid project (no client was built)."""


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
            except gexc.AlreadyExists:
                if attempt and (snapshot := ref.get()).exists and snapshot.to_dict() == body:
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
        blob = self._bucket.blob(_safe_key(key))
        try:
            blob.upload_from_string(data, content_type="application/octet-stream", if_generation_match=0)
        except gexc.PreconditionFailed:
            raise FileExistsError(key) from None

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
    """A `tilo_archive.archive.Store`: line `n` of a run is the create-only object `{org}/{run}/{n:08d}.jsonl`."""

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
        for _ in range(_ATTEMPTS):
            with self._lock:
                index = self._next.get((org_id, run_id))
            if index is None:
                index = max((n for n, _ in self._objects(prefix)), default=0) + 1
            blob = self._bucket.blob(f"{prefix}{index:08d}.jsonl")
            try:
                blob.upload_from_string(data, content_type="application/x-ndjson", if_generation_match=0)
            except gexc.PreconditionFailed:  # another writer took this index: look again
                with self._lock:
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
    `str_redactor` propagates, so the archive writes nothing (fail closed)."""

    def redact(value: Any) -> Any:
        if isinstance(value, str):
            return str_redactor(value)
        if isinstance(value, Mapping):
            return {(redact(k) if isinstance(k, str) else k): redact(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [redact(v) for v in value]
        return value

    return redact


# --- the doors ---------------------------------------------------------------------------------------------------


def _default_firestore(project: str) -> Any:
    return firestore.Client(project=project)


def _default_storage(project: str) -> Any:
    from google.cloud.storage import Client  # noqa: PLC0415 - imported only when a door builds its client

    return Client(project=project)


def _settings(source: Mapping[str, str], switch: str, bucket_var: str, emulators: Sequence[str]) -> tuple[str, str]:
    """(project, bucket) for a door, or `RunStoreNotConfigured`. Outside Cloud Run (no `K_SERVICE`) the default
    factories open only an emulator and a `demo-` project; `emulators` names the hosts they need."""
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
    if (
        emulators
        and not source.get("K_SERVICE")
        and not (project.startswith("demo-") and all(source.get(h) for h in emulators))
    ):
        raise RunStoreNotConfigured(f"outside Cloud Run {switch} opens only an emulator on a demo- project")
    return project, bucket


def open_artifact_store(
    env: Mapping[str, str] | None = None,
    *,
    firestore_client_factory: Callable[[str], Any] | None = None,
    storage_client_factory: Callable[[str], Any] | None = None,
    redactor: Callable[[str], str],
    clock: Callable[[], datetime] | None = None,
    archive_lookup: Callable[[Any, str], str | None] | None = None,
    alert_sink: Callable[[dict[str, Any]], None] | None = None,
) -> ArtifactStore:
    """Records in Firestore, bytes in GCS: `TILO_ARTIFACTS_STORE=gcs`, `TILO_ARTIFACTS_BUCKET`, a project.
    An injected factory opens anywhere; a default one follows the emulator rule above."""
    source = os.environ if env is None else env
    hosts = ["FIRESTORE_EMULATOR_HOST"] if firestore_client_factory is None else []
    hosts += ["STORAGE_EMULATOR_HOST"] if storage_client_factory is None else []
    project, bucket = _settings(source, "TILO_ARTIFACTS_STORE", "TILO_ARTIFACTS_BUCKET", hosts)
    fs_client = (firestore_client_factory or _default_firestore)(project)
    storage_client = (storage_client_factory or _default_storage)(project)

    def alert(payload: dict[str, Any]) -> None:
        logger.warning("artifact alert: %s", payload.get("summary", "raised"))  # ids only, never content

    return ArtifactStore(
        FirestoreMetaBackend(fs_client, collection_root="orgs"),
        GcsBlobBackend(storage_client.bucket(bucket)),
        clock=clock or (lambda: datetime.now(UTC)),
        redactor=redactor,
        archive_lookup=archive_lookup or (lambda scope, ref: None),
        alert_sink=alert_sink or alert,
    )


def open_run_archive(
    env: Mapping[str, str] | None = None,
    *,
    storage_client_factory: Callable[[str], Any] | None = None,
    redactor: Callable[[Any], Any],
) -> Callable[..., RunArchive]:
    """`open_archive(*, org_id, run_id) -> RunArchive` over the `archive` bucket: `TILO_ARCHIVE_STORE=gcs`,
    `TILO_ARCHIVE_BUCKET`, `TILO_FIRESTORE_PROJECT` (the one project id both stores share)."""
    source = os.environ if env is None else env
    hosts = ("STORAGE_EMULATOR_HOST",) if storage_client_factory is None else ()
    project, bucket = _settings(source, "TILO_ARCHIVE_STORE", "TILO_ARCHIVE_BUCKET", hosts)
    store = GcsArchiveStore((storage_client_factory or _default_storage)(project).bucket(bucket))

    def open_archive(*, org_id: str, run_id: str) -> RunArchive:
        return RunArchive(store, org_id=org_id, run_id=run_id, redactor=redactor)

    return open_archive
