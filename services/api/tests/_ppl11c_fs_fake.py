"""A small in-memory stand-in for the Firestore client, for the PPL-11c-FS-1c tests (API_PPL_11c_FS1c.md section 1).

It models only what `tilo_api.people_firestore` calls, with Firestore's own write semantics, in the one mode the
emulator cannot give us: **optimistic, with no read locks**. A read inside a transaction returns what is stored at that
moment and nothing is checked at commit about what was read; the only things that can stop a write are the
preconditions the writer put on it (`create` fails `AlreadyExists` if the document exists, `update` fails `NotFound` if
it does not). A store whose uniqueness rests on the emulator's pessimistic read locks passes every other test and fails
here, which is the point (issue #577 item 2).

* `FakeFirestore.document(path)` / `.collection(path)` / `.transaction()` / `.write_option(**kw)` like a client.
* A transaction is a real `google.cloud.firestore_v1.transaction.Transaction` subclass, so `firestore.transactional`
  drives it exactly as it drives a real one (begin, run the callable, commit, rollback on error); its writes are
  buffered and applied atomically at commit, or not at all.
* `rival_after_read(path, doc)` registers a one-shot rival: right after the first read of `path` (the snapshot the
  reader got is already stale) the rival writes `doc` there, as another instance of the service would between our
  read and our commit. `rival_after_read(path, docs)` also takes a `{path: doc}` map of several documents.
* `attempted_ops` lists every write the transactions tried to commit, `(kind, path)`, successful or not.

No network, no credentials, no I/O. Not business logic: nothing here knows what a person or a reservation is.
"""

from __future__ import annotations

import copy
import itertools
import time
from collections.abc import Mapping
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud.firestore_v1 import ReadAfterWriteError
from google.cloud.firestore_v1.base_transaction import BaseTransaction
from google.cloud.firestore_v1.transaction import Transaction

_CLOCK = itertools.count(1)


def _dig(data: Mapping[str, Any] | None, field_path: str) -> Any:
    current: Any = data
    for part in field_path.split("."):
        current = current[part]
    return current


def _refuse_read_after_write(transaction: Any) -> None:
    """The SDK refuses (client side, `ReadAfterWriteError`) a transactional read once the transaction has a buffered
    write; the emulator and the server say the same, so a store that interleaves them works nowhere."""
    if transaction is not None and getattr(transaction, "_ops", None):
        raise ReadAfterWriteError("Attempted read after write in a transaction.")


class FakeSnapshot:
    def __init__(self, path: str, data: Mapping[str, Any] | None) -> None:
        self.id = path.rsplit("/", 1)[-1]
        self.reference_path = path
        self._data = None if data is None else copy.deepcopy(dict(data))
        self.update_time = next(_CLOCK)

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else copy.deepcopy(self._data)

    def get(self, field_path: str) -> Any:
        if self._data is None:
            raise KeyError(field_path)
        return copy.deepcopy(_dig(self._data, field_path))


class FakeRef:
    def __init__(self, db: FakeFirestore, path: str) -> None:
        self._db, self.path, self.id = db, path, path.rsplit("/", 1)[-1]

    def get(self, transaction: Any = None, **_: Any) -> FakeSnapshot:
        _refuse_read_after_write(transaction)
        return self._db.read(self.path)

    # Direct (non-transactional) writes: one operation, atomic, with its own precondition.
    def create(self, data: Mapping[str, Any]) -> None:
        self._db.commit([("create", self.path, dict(data))])

    def set(self, data: Mapping[str, Any]) -> None:
        self._db.commit([("set", self.path, dict(data))])

    def update(self, data: Mapping[str, Any], option: Any = None) -> None:
        self._db.commit([("update", self.path, dict(data))])

    def delete(self, option: Any = None) -> None:
        self._db.commit([("delete", self.path, None)])


class FakeQuery:
    def __init__(self, db: FakeFirestore, prefix: str, limit: int | None = None) -> None:
        self._db, self._prefix, self._limit = db, prefix, limit

    def limit(self, count: int) -> FakeQuery:
        return FakeQuery(self._db, self._prefix, count)

    def where(self, *, filter: Any) -> FakeQuery:  # noqa: A002 - the library's keyword
        raise NotImplementedError("the fake serves the person store's calls only (no index queries)")

    def stream(self, transaction: Any = None, **_: Any) -> Any:
        _refuse_read_after_write(transaction)
        paths = sorted(p for p in self._db.docs if p.startswith(self._prefix) and "/" not in p[len(self._prefix) :])
        for path in paths[: self._limit]:
            yield self._db.read(path)


class FakeTransaction(Transaction):
    """A real `Transaction` with the network taken out: writes are buffered, `_commit` applies them atomically."""

    def __init__(self, db: FakeFirestore) -> None:
        BaseTransaction.__init__(self, 5, False)
        self._db = db
        self._ops: list[tuple[str, str, dict[str, Any] | None]] = []

    def _clean_up(self) -> None:
        self._id = None
        self._ops = []

    def _begin(self, retry_id: bytes | None = None) -> None:
        self._ops = []
        self._id = b"fake-transaction"

    def _commit(self) -> list:
        ops, self._ops, self._id = self._ops, [], None
        self._db.commit(ops)
        return []

    def _rollback(self) -> None:
        self._ops, self._id = [], None

    # buffered writes (the references are `FakeRef`s)
    def create(self, reference: FakeRef, document_data: Mapping[str, Any]) -> None:  # type: ignore[override]
        self._ops.append(("create", reference.path, dict(document_data)))

    def set(self, reference: FakeRef, document_data: Mapping[str, Any], merge: bool = False) -> None:  # type: ignore[override]
        self._ops.append(("set", reference.path, dict(document_data)))

    def update(self, reference: FakeRef, field_updates: Mapping[str, Any], option: Any = None) -> None:  # type: ignore[override]
        self._ops.append(("update", reference.path, dict(field_updates)))

    def delete(self, reference: FakeRef, option: Any = None) -> None:  # type: ignore[override]
        self._ops.append(("delete", reference.path, None))


class FakeFirestore:
    """The client: documents by path, optimistic (no read locks, nothing about reads checked at commit)."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.attempted_ops: list[tuple[str, str]] = []
        self._rivals: list[tuple[str, dict[str, dict[str, Any]]]] = []

    # -- the client surface the people adapter uses ------------------------------------------------------------------
    def document(self, path: str) -> FakeRef:
        return FakeRef(self, path)

    def collection(self, path: str) -> FakeQuery:
        return FakeQuery(self, path.rstrip("/") + "/")

    def transaction(self, **_: Any) -> FakeTransaction:
        return FakeTransaction(self)

    def write_option(self, **_: Any) -> object:
        return object()

    # -- state ------------------------------------------------------------------------------------------------------
    def read(self, path: str) -> FakeSnapshot:
        snapshot = FakeSnapshot(path, self.docs.get(path))
        for rival in [r for r in self._rivals if r[0] == path]:
            self._rivals.remove(rival)
            self.docs.update(copy.deepcopy(rival[1]))  # after the snapshot above: the reader's answer is stale
        return snapshot

    def raw(self, path: str) -> dict[str, Any] | None:
        found = self.docs.get(path)
        return None if found is None else copy.deepcopy(found)

    def put(self, path: str, doc: Mapping[str, Any]) -> None:
        """Arranges state directly (no precondition, not an attempted op)."""
        self.docs[path] = copy.deepcopy(dict(doc))

    def rival_after_read(
        self, path: str, doc: Mapping[str, Any] | None = None, *, docs: Mapping[str, Any] | None = None
    ):
        """One-shot: right after the first read of `path`, `doc` (or every `{path: doc}` of `docs`) is written."""
        self._rivals.append((path, copy.deepcopy(dict(docs if docs is not None else {path: doc}))))

    def commit(self, ops: list[tuple[str, str, dict[str, Any] | None]]) -> None:
        """Applies the writes in order, all or nothing, each with Firestore's precondition."""
        self.attempted_ops.extend((kind, path) for kind, path, _ in ops)
        staged = dict(self.docs)  # shallow: a document is replaced below, never changed in place
        for kind, path, data in ops:
            if kind == "create":
                if path in staged:
                    raise gexc.AlreadyExists(
                        f"Document already exists: projects/p/databases/(default)/documents/{path}"
                    )
                staged[path] = copy.deepcopy(data or {})
            elif kind == "set":
                staged[path] = copy.deepcopy(data or {})
            elif kind == "update":
                if path not in staged:
                    raise gexc.NotFound(f"No document to update: projects/p/databases/(default)/documents/{path}")
                staged[path] = {**staged[path], **copy.deepcopy(data or {})}
            else:
                staged.pop(path, None)
        self.docs = staged


class SlowPersons:
    """A person store whose `get` and `list` take a snapshot and then sleep before they answer, so the answer is stale
    by the time the caller acts on it (as a database read is); every other attribute goes straight through."""

    def __init__(self, inner: Any, delay: float = 0.1) -> None:
        self._inner, self._delay = inner, delay

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def get(self, *args: Any, **kwargs: Any) -> Any:
        answer = self._inner.get(*args, **kwargs)
        time.sleep(self._delay)
        return answer

    def list(self, *args: Any, **kwargs: Any) -> Any:
        answer = self._inner.list(*args, **kwargs)
        time.sleep(self._delay)
        return answer
