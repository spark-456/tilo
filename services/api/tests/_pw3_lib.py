"""PROD-WIRE slice 3 helpers (one Firestore client per process). Kept out of conftest.py
under a package-unique name, as `_pw1b_lib.py` is.

Pinned interface (every test of slice 3), all in the new module `tilo_api.prod`:

- `firestore_client(project: str) -> Any`: the process's one Firestore client for `project`. Reads `os.environ` on
  every call and applies, in order: the project matches `store_door.GCP_PROJECT`; `K_SERVICE` set (presence, even
  the empty string) together with a `FIRESTORE_EMULATOR_HOST` refuses; with `K_SERVICE` unset only an emulator host
  AND a `demo-` project opens; `GOOGLE_CLOUD_PROJECT`, if set, must equal `project`. A refusal raises
  `FirestoreNotConfigured` (a `store_door.ApiStoreNotConfigured` and a `people_firestore.PeopleStoreNotConfigured`).
  Then one client per project per process, built by the module attribute `build_client(project)` (default
  `google.cloud.firestore.Client(project=project)`; tests replace it), single-flight under a lock; a builder that
  raises is not cached and surfaces as `FirestoreUnavailable` (a `store_door.ApiStoreUnavailable`, no exception text).
  `reset()` forgets every cached client.
- `durable_store.deployed()` and `deps.get_people_stores()` both obtain their client from `prod.firestore_client`;

`Pw3` is the per-test rig: a cold process, no ambient config, and the real `google.cloud.firestore.Client` replaced by
a spy, so no test can reach a real client. A test calls `pw3.use(builder)` to import `tilo_api.prod` (a missing module
is a failing assertion, not a collection error) and install its fake builder. Nothing here is business logic.
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gexc

PROJECT = "tilo-dev-test"
DEMO = "demo-pw3"
EMULATOR = "127.0.0.1:8080"
SENTINEL = "pw3-secret-looking-detail"  # carried in a builder's exception: it must never reach a message
AMBIENT = (
    "K_SERVICE",
    "CLOUD_RUN_JOB",
    "FIRESTORE_EMULATOR_HOST",
    "GOOGLE_CLOUD_PROJECT",
    "TILO_API_STORE",
    "TILO_PEOPLE_STORE",
    "TILO_FIRESTORE_PROJECT",
    "TILO_SCHEDULES_STORE",
    "TILO_API_DEV",
    "TILO_PEOPLE_BOOTSTRAP_UID",
    "LIVE",
)


def import_prod() -> Any:
    """`tilo_api.prod`, or a failing assertion naming it (so every test fails for the one right reason)."""
    try:
        return importlib.import_module("tilo_api.prod")
    except ImportError as exc:
        pytest.fail(f"PROD-WIRE 3: the module tilo_api.prod does not exist yet ({exc})", pytrace=False)


def reset_prod() -> None:
    """Forget every cached client, if the module is already loaded (it may not exist yet)."""
    module = sys.modules.get("tilo_api.prod")
    if module is not None and hasattr(module, "reset"):
        module.reset()


class Builder:
    """A fake `prod.build_client`: records each call and returns a fresh fake client per call (a MagicMock unless
    `make` says otherwise), optionally slowly or failing."""

    def __init__(self, *, delay: float = 0.0, make: Any = None) -> None:
        self.delay, self.fail, self.make = delay, False, make
        self.calls: list[str] = []
        self.returned: list[Any] = []
        self._lock = threading.Lock()

    def __call__(self, project: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            self.calls.append(project)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError(f"cannot reach the metadata server ({SENTINEL})")
        client = self.make() if self.make else MagicMock(name="firestore_client")
        with self._lock:
            self.returned.append(client)
        return client


class RealClientSpy:
    """Stands in for `google.cloud.firestore.Client`: records the call, never builds anything real."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.made = object()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.made


@dataclass
class Pw3:
    monkeypatch: pytest.MonkeyPatch
    real: RealClientSpy = field(default_factory=RealClientSpy)

    def env(self, **values: str) -> None:
        for name, value in values.items():
            self.monkeypatch.setenv(name, value)

    def deployed(self, project: str = PROJECT, *, api: bool = False, people: bool = False, **more: str) -> None:
        """A Cloud Run instance: `K_SERVICE`, the project pinned, and the switches asked for."""
        values = {"K_SERVICE": "tilo-api", "GOOGLE_CLOUD_PROJECT": project, "TILO_FIRESTORE_PROJECT": project}
        if api:
            values["TILO_API_STORE"] = "firestore"
        if people:
            values["TILO_PEOPLE_STORE"] = "firestore"
        self.env(**values, **more)

    def laptop(self, project: str = DEMO, *, emulator: str | None = EMULATOR, **more: str) -> None:
        values = {"TILO_FIRESTORE_PROJECT": project, **more}
        if emulator is not None:
            values["FIRESTORE_EMULATOR_HOST"] = emulator
        self.env(**values)

    def use(self, builder: Any = None) -> Any:
        """Import `tilo_api.prod` (fails the test if it is missing) and install `builder` as its `build_client`."""
        module = import_prod()
        if builder is not None:
            self.monkeypatch.setattr(module, "build_client", builder)
        return module


def make_pw3(monkeypatch: pytest.MonkeyPatch) -> Pw3:
    from google.cloud import firestore
    from tilo_api import deps, durable_store

    for name in AMBIENT:
        monkeypatch.delenv(name, raising=False)
    rig = Pw3(monkeypatch)
    monkeypatch.setattr(firestore, "Client", rig.real)
    monkeypatch.setattr(durable_store, "_opened", {})
    deps.get_people_stores.cache_clear()
    reset_prod()
    return rig


# -- a small fake Firestore client for the access store -------------------------------------------------------------


class _Snapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = None if data is None else dict(data)

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else dict(self._data)

    def get(self, field_path: str) -> Any:
        if self._data is None:
            raise KeyError(field_path)
        return self._data[field_path]


class _Ref:
    def __init__(self, client: FakeClient, path: str) -> None:
        self._client, self.path, self.id = client, path, path.rsplit("/", 1)[-1]

    def get(self, *args: Any, **kwargs: Any) -> _Snapshot:
        self._client.ops.append(("get", self.path))
        time.sleep(self._client.read_delay)  # widens a read-then-write race, if a store has one
        with self._client.lock:
            return _Snapshot(self._client.docs.get(self.path))

    def create(self, data: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        self._client.ops.append(("create", self.path))
        with self._client.lock:
            if self.path in self._client.docs:
                raise gexc.AlreadyExists(f"document {self.path} already exists")
            self._client.docs[self.path] = dict(data)
        return object()

    def __getattr__(self, name: str) -> Any:  # set, update, delete, ...: recorded, and refused
        if name.startswith("__"):
            raise AttributeError(name)

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            self._client.ops.append((name, self.path))
            raise AssertionError(f"the access store must never call .{name}() (first write wins, never an overwrite)")

        return forbidden


class _Collection:
    def __init__(self, client: FakeClient, path: str) -> None:
        self._client, self._path = client, path

    def document(self, doc_id: str) -> _Ref:
        self._client.ops.append(("ref", f"{self._path}/{doc_id}"))
        return _Ref(self._client, f"{self._path}/{doc_id}")


class FakeClient:
    """Models only what the access store may call: `document(path)` / `collection(path).document(id)`, then `get()`
    and `create()` (atomic: `AlreadyExists` if the document exists). Any other client or document method is
    recorded in `ops` and raises, so a `set`, an `update`, a `delete` or a transaction fails the test that sees it."""

    def __init__(self, docs: dict[str, dict[str, Any]] | None = None, *, read_delay: float = 0.0) -> None:
        self.docs: dict[str, dict[str, Any]] = dict(docs or {})
        self.ops: list[tuple[str, str]] = []
        self.lock = threading.Lock()
        self.read_delay = read_delay

    def document(self, path: str) -> _Ref:
        self.ops.append(("ref", path))
        return _Ref(self, path)

    def collection(self, path: str) -> _Collection:
        self.ops.append(("ref", path))
        return _Collection(self, path)

    def __getattr__(self, name: str) -> Any:  # transaction(), batch(), ...
        if name.startswith("__"):
            raise AttributeError(name)

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            self.ops.append((name, ""))
            raise AssertionError(f"the access store must not call client.{name}()")

        return forbidden

    def writes(self) -> list[tuple[str, str]]:
        return [op for op in self.ops if op[0] not in {"get", "ref", "create"}]


def threads(count: int, work: Any) -> list[Any]:
    """Runs `work(i)` on `count` threads released together; returns each result (or the exception it raised)."""
    barrier, out = threading.Barrier(count), [None] * count

    def run(i: int) -> None:
        barrier.wait(timeout=10)
        try:
            out[i] = work(i)
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            out[i] = exc

    pool = [threading.Thread(target=run, args=(i,)) for i in range(count)]
    for t in pool:
        t.start()
    for t in pool:
        t.join(timeout=30)
    return out
