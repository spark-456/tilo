"""PROD-WIRE slice 5a helpers (the durable Treasury ledger). Kept out of conftest.py under a package-unique name, as
`_pw3_lib.py` is. Nothing here is business logic.

Pinned interface (every test of slice 5a):

- `tilo_api.prod.FirestoreLedger(client, org_id="org_tilo")`, documents at `orgs/{org}/ledger/{entry_id}` holding the
  `LedgerEntry` fields (`kind, run, user, org, at, step, credits, usage, price_effective_date, price_source, day`),
  JSON-safe: `at` and `day` ISO strings, `usage` the dict `{"profile", "tokens_in", "tokens_out"}`.
  `append(entry, *, entry_id)`, `entries()`, `append_entry(entry)`; `prod.LedgerConflict`; library errors are
  `prod.FirestoreUnavailable`.
- The client calls the fake below models (and refuses everything else, so a `set`, `update`, `delete`, transaction,
  batch or collection-group read fails the test that sees it): `client.document(path)` or `client.collection(path)`
  (a slash path, or `.document(id)`), a reference's `get()` and atomic `create(data)` (`AlreadyExists` when the
  document exists), and a collection's `stream()` / `get()` (every document directly in it, each snapshot with `.id`,
  `.exists`, `.to_dict()`). `create` stores a JSON round trip of the body, so a body that is not JSON-safe (a datetime,
  a date, a dataclass) fails there, the way the contract says it must.
- `tilo_api.cost_entries.entry_from_cost_event(event, owner, *, org=deps.ORG_ID, usage=None) -> LedgerEntry | None`:
  the one conversion of a committed cost event (credits > 0) to its `commit` entry. Dev mode passes
  `usage=dev_run.UNIT_USAGE`; the deployed writer passes nothing (an event records no usage, and none is invented).
- `world_writer.WorldWriterAdapter(store, backend, *, org_id, clock, lease_s, ledger=None)`: `ledger` is any object
  with `append(entry, *, entry_id)` (a `FirestoreLedger` in `durable_store.deployed()`, on `opened.client`).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from google.api_core import exceptions as gexc
from tilo_metering import LedgerEntry
from tilo_metering.prices import Usage

SENTINEL = "pw5-sentinel-detail"  # carried in an exception message or a bad value: it must never reach a log or a body
AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def import_attr(module: str, name: str) -> Any:
    """`module.name`, or a failing assertion naming it (the test fails for the right reason, not at collection)."""
    import importlib

    try:
        found = importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(f"PROD-WIRE 5a: the module {module} does not exist yet ({exc})", pytrace=False)
    if not hasattr(found, name):
        pytest.fail(f"PROD-WIRE 5a: {module}.{name} does not exist yet", pytrace=False)
    return getattr(found, name)


def firestore_ledger() -> Any:
    return import_attr("tilo_api.prod", "FirestoreLedger")


def entry_from_cost_event() -> Any:
    return import_attr("tilo_api.cost_entries", "entry_from_cost_event")


def make_entry(**over: Any) -> LedgerEntry:
    fields: dict[str, Any] = {
        "kind": "commit", "run": "r_pw5_1", "user": "u_pw5_owner", "org": "org_tilo", "at": AT, "step": "U1",
        "credits": 12.5, "usage": Usage("flash-38", 1000, 500), "price_effective_date": "2026-06-01",
        "price_source": "Fake price sheet for tests.", "day": date(2026, 6, 1),
    }  # fmt: skip
    return LedgerEntry(**(fields | over))


# -- a small fake Firestore client for the ledger ---------------------------------------------------------------------


class Snap:
    def __init__(self, doc_id: str, data: dict[str, Any] | None) -> None:
        self.id, self._data = doc_id, None if data is None else json.loads(json.dumps(data))

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else json.loads(json.dumps(self._data))


class Ref:
    def __init__(self, client: LedgerClient, path: str) -> None:
        self._client, self.path, self.id = client, path, path.rsplit("/", 1)[-1]

    def get(self, *args: Any, **kwargs: Any) -> Snap:
        self._client.ops.append(("get", self.path))
        self._client.maybe_fail("get")
        time.sleep(self._client.read_delay)  # widens a read-then-write race, if a store has one
        with self._client.lock:
            return Snap(self.id, self._client.docs.get(self.path))

    def create(self, data: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
        self._client.ops.append(("create", self.path))
        self._client.maybe_fail("create")
        stored = json.loads(json.dumps(data))  # TypeError for a datetime, a date or a dataclass
        with self._client.lock:
            if self.path in self._client.docs:
                raise gexc.AlreadyExists(f"document {self.path} already exists")
            self._client.docs[self.path] = stored
        return object()

    def collection(self, name: str) -> Coll:
        self._client.ops.append(("ref", f"{self.path}/{name}"))
        return Coll(self._client, f"{self.path}/{name}")

    def __getattr__(self, name: str) -> Any:  # set, update, delete, ...: recorded, and refused
        if name.startswith("__"):
            raise AttributeError(name)

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            self._client.ops.append((name, self.path))
            raise AssertionError(f"the ledger must never call .{name}() (append-only: create, then read back)")

        return forbidden


class Coll:
    def __init__(self, client: LedgerClient, path: str) -> None:
        self._client, self._path = client, path

    def document(self, doc_id: str) -> Ref:
        self._client.ops.append(("ref", f"{self._path}/{doc_id}"))
        return Ref(self._client, f"{self._path}/{doc_id}")

    def stream(self, *args: Any, **kwargs: Any) -> list[Snap]:
        self._client.ops.append(("stream", self._path))
        self._client.maybe_fail("stream")
        prefix = self._path + "/"
        with self._client.lock:
            found = [
                (p, d) for p, d in self._client.docs.items() if p.startswith(prefix) and "/" not in p[len(prefix) :]
            ]
        return [Snap(p.rsplit("/", 1)[-1], d) for p, d in found]

    get = stream

    def __getattr__(self, name: str) -> Any:  # where, order_by, list_documents, add, ...
        if name.startswith("__"):
            raise AttributeError(name)

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            self._client.ops.append((name, self._path))
            raise AssertionError(f"the ledger reads a collection with .stream() (or .get()), not .{name}()")

        return forbidden


class LedgerClient:
    """Models only what the ledger may call. A fault can be armed per operation (`fail("create", exc)`)."""

    def __init__(self, docs: dict[str, dict[str, Any]] | None = None, *, read_delay: float = 0.0) -> None:
        self.docs: dict[str, dict[str, Any]] = dict(docs or {})
        self.ops: list[tuple[str, str]] = []
        self.lock = threading.Lock()
        self.read_delay = read_delay
        self._faults: dict[str, Callable[[], BaseException]] = {}

    def fail(self, op: str, exc: BaseException | Callable[[], BaseException] | None) -> None:
        """Arms `op` ("get", "create", "stream") to raise `exc` every time; `None` disarms it."""
        if exc is None:
            self._faults.pop(op, None)
        else:
            self._faults[op] = exc if callable(exc) else (lambda: exc)  # type: ignore[assignment]

    def maybe_fail(self, op: str) -> None:
        if op in self._faults:
            raise self._faults[op]()

    def document(self, path: str) -> Ref:
        self.ops.append(("ref", path))
        return Ref(self, path)

    def collection(self, path: str) -> Coll:
        self.ops.append(("ref", path))
        return Coll(self, path)

    def __getattr__(self, name: str) -> Any:  # transaction(), batch(), collection_group(), ...
        if name.startswith("__"):
            raise AttributeError(name)

        def forbidden(*args: Any, **kwargs: Any) -> Any:
            self.ops.append((name, ""))
            raise AssertionError(f"the ledger must not call client.{name}() (one org's collection, create only)")

        return forbidden

    def writes(self) -> list[tuple[str, str]]:
        return [op for op in self.ops if op[0] not in {"get", "ref", "create", "stream"}]

    def ledger_docs(self, org: str = "org_tilo") -> dict[str, dict[str, Any]]:
        prefix = f"orgs/{org}/ledger/"
        return {p[len(prefix) :]: d for p, d in self.docs.items() if p.startswith(prefix)}


def doc_path(entry_id: str, org: str = "org_tilo") -> str:
    return f"orgs/{org}/ledger/{entry_id}"


def stored_body(entry: LedgerEntry, entry_id: str = "e_scratch") -> dict[str, Any]:
    """What the ledger under test stores for `entry` (it writes to a scratch client; the fake JSON round-trips it)."""
    client = LedgerClient()
    firestore_ledger()(client).append(entry, entry_id=entry_id)
    return client.docs[doc_path(entry_id)]


# -- the adapter's ledger fake --------------------------------------------------------------------------------


class RecordingLedger:
    """A stand-in for `FirestoreLedger` on the adapter: idempotent by `entry_id` (an identical entry is a no-op, another
    body raises), records every call, and can fail on demand. `seen_at_append` lets a test look at the world as it
    was when the ledger was called."""

    def __init__(self) -> None:
        self.docs: dict[str, LedgerEntry] = {}
        self.calls: list[tuple[str, LedgerEntry]] = []
        self.fail: BaseException | None = None
        self.seen_at_append: list[Any] = []
        self.probe: Callable[[], Any] | None = None

    def append(self, entry: LedgerEntry, *, entry_id: str) -> None:
        self.calls.append((entry_id, entry))
        if self.probe is not None:
            self.seen_at_append.append(self.probe())
        if self.fail is not None:
            raise self.fail
        held = self.docs.get(entry_id)
        if held is None:
            self.docs[entry_id] = entry
        elif held != entry:
            raise RuntimeError("conflict")
