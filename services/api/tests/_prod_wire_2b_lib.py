"""Helpers for the PROD-WIRE 2b tests (durable artifact and raw-archive backends; ADR-0018 T8, FR-MEM-04).

`FakeBucket` mimics the subset of google-cloud-storage's `Bucket`/`Blob` that the backends may use: `blob(name)`,
`upload_from_string(data, if_generation_match=)` (412 `PreconditionFailed`), `download_as_bytes()` (`NotFound`),
`delete()` (a blob listed or built with a generation removes that generation; without one it removes the live object,
or archives it in a versioned bucket), `list_blobs(prefix=, versions=)` and `delete_blob(name, generation=)`.
`lose_reply` stages the 412 a retried create-only upload meets when its first attempt saved the bytes but the answer
was lost (google-cloud-storage retries a generation-matched upload by default). There is no official GCS emulator,
so the real-GCS check is the deployed smoke (PR4). Names are unique to this ticket because test directories have no
`__init__.py` (global module names). No network, no secret.
"""

from __future__ import annotations

import sys
import threading
import types
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import firestore

try:  # google-cloud-storage is not a dependency yet (PROD-WIRE 2b adds it); the tests must run with or without it
    from google.cloud import storage as real_storage
except ImportError:
    real_storage = None

PROJECT, ORG, RUN = "tilo-test-project", "org_acme", "r_run1"
SECRET = "fake-secret-" + "".join(["0x", "DEAD", "BEEF"])  # assembled at runtime (CLAUDE.md)


def mask(text: str) -> str:
    return text.replace(SECRET, "[REDACTED]")


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str, generation: int | None = None) -> None:
        self.bucket, self.name, self.generation = bucket, name, generation

    def upload_from_string(
        self, data, content_type="text/plain", *, if_generation_match=None, timeout=None, retry=None
    ):
        self.bucket._upload(self.name, data, if_generation_match)

    def download_as_bytes(self, *, timeout=None, retry=None) -> bytes:
        return self.bucket._live(self.name)["data"]

    def delete(self, *, timeout=None, retry=None) -> None:
        self.bucket._delete(self.name, self.generation)


class FakeBucket:
    def __init__(self, name: str = "fake-bucket", *, versioned: bool = True) -> None:
        self.name, self.versioned, self._lock, self._next = name, versioned, threading.Lock(), 1
        self._objects: dict[str, list[dict[str, Any]]] = {}
        self.upload_log: list[tuple[str, Any]] = []  # (name, if_generation_match) of every upload attempt
        self.before_upload = None  # a hook called with the name before each upload
        self.lose_reply = None  # a hook: True saves the upload, then answers 412 (a retried, lost-reply first attempt)

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def list_blobs(self, prefix=None, *, versions=False, max_results=None, page_size=None, timeout=None, retry=None):
        with self._lock:
            found = [(n, g["generation"]) for n, gens in self._objects.items() for g in gens if g["live"] or versions]
        return [FakeBlob(self, n, gen) for n, gen in sorted(found) if n.startswith(prefix or "")][:max_results]

    def delete_blob(self, blob_name: str, *, generation=None, timeout=None, retry=None) -> None:
        self._delete(blob_name, generation)

    def _live(self, name: str) -> dict[str, Any]:
        with self._lock:
            for g in self._objects.get(name, []):
                if g["live"]:
                    return g
        raise gexc.NotFound(f"404 {name}")

    def _upload(self, name: str, data: bytes | str, match: int | None) -> None:
        if self.before_upload is not None:
            self.before_upload(name)
        with self._lock:
            self.upload_log.append((name, match))
            gens = self._objects.setdefault(name, [])
            live = next((g for g in gens if g["live"]), None)
            if match == 0 and live is not None or match not in (None, 0) and (live or {}).get("generation") != match:
                raise gexc.PreconditionFailed(f"412 {name}")
            if live is not None:
                live["live"] = False
            if live is not None and not self.versioned:
                gens.remove(live)
            gens.append({"generation": self._next, "data": data.encode() if isinstance(data, str) else bytes(data),
                         "live": True})  # fmt: skip
            self._next += 1
        if self.lose_reply is not None and self.lose_reply(name):
            raise gexc.PreconditionFailed(f"412 {name} (our own first attempt landed; its answer was lost)")

    def _delete(self, name: str, generation: int | None) -> None:
        with self._lock:
            gens = self._objects.get(name, [])
            hit = next((g for g in gens if g["live"]), None) if generation is None else next(
                (g for g in gens if g["generation"] == generation), None)  # fmt: skip
            if hit is None:
                raise gexc.NotFound(f"404 {name}")
            if generation is None and self.versioned:
                hit["live"] = False
            else:
                gens.remove(hit)
            if not gens:
                self._objects.pop(name, None)

    # -- what a test may look at or do behind the backend's back ------------------------------------------------------
    def live_names(self) -> list[str]:
        return [b.name for b in self.list_blobs()]

    def generations(self, name: str) -> list[int]:
        return [b.generation for b in self.list_blobs(name, versions=True) if b.name == name]

    def live_bytes(self, name: str) -> bytes:
        return self._live(name)["data"]

    def plant(self, name: str, data: bytes) -> None:
        self._upload(name, data, 0)
        self.upload_log.clear()

    def tamper(self, name: str, data: bytes) -> None:
        self._live(name)["data"] = data  # the same generation with other bytes: what an attacker with write access does

    def drop(self, name: str) -> None:
        with self._lock:
            self._objects.pop(name, None)


class FakeStorageClient:
    """`bucket(name)` only builds a handle (no I/O); `get_bucket` and `lookup_bucket` would need `storage.buckets.get`,
    which the api's roles do not grant, so a backend that calls them fails here."""

    def __init__(self) -> None:
        self.requested: list[str] = []
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str, user_project=None) -> FakeBucket:
        self.requested.append(name)
        return self.buckets.setdefault(name, FakeBucket(name))

    def get_bucket(self, *args, **kwargs):
        raise AssertionError("get_bucket does I/O and needs storage.buckets.get")

    lookup_bucket = get_bucket


class ClientSpy:
    """Records its calls and returns `result`; with `result=None` it is a bomb (a cloud client must not be built)."""

    def __init__(self, result: Any = None) -> None:
        self.result, self.calls = result, []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        if self.result is None:
            raise AssertionError("a cloud client was built")
        return self.result


def patch_clients(monkeypatch, firestore_client: Any = None, storage_client: Any = None) -> tuple[ClientSpy, ClientSpy]:
    """Replace `google.cloud.firestore.Client` and `google.cloud.storage.Client` (a stand-in module if google-cloud-
    storage is not installed). A `None` client makes that class a bomb."""
    fs_spy, st_spy = ClientSpy(firestore_client), ClientSpy(storage_client)
    monkeypatch.setattr(firestore, "Client", fs_spy)
    module = real_storage
    if module is None:
        module = types.ModuleType("google.cloud.storage")
        monkeypatch.setitem(sys.modules, "google.cloud.storage", module)
        monkeypatch.setattr(sys.modules["google.cloud"], "storage", module, raising=False)
    monkeypatch.setattr(module, "Client", st_spy, raising=False)
    return fs_spy, st_spy


def race(work, n: int = 8) -> list[str]:
    """Run `work(i)` on `n` threads released together; 'ok', 'exists' for FileExistsError, else the error's type."""
    outcomes, barrier = [], threading.Barrier(n, timeout=30)

    def run(i: int) -> None:
        barrier.wait()
        try:
            work(i)
            outcomes.append("ok")
        except FileExistsError:
            outcomes.append("exists")
        except Exception as exc:  # noqa: BLE001
            outcomes.append(type(exc).__name__)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    return outcomes
