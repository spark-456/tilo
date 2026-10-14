"""A Firestore stand-in for the ADR35-L2 outbox store tests: `_ppl11c_fs_fake.FakeFirestore` plus what a Firestore
transaction gives that one lacks, and the query surface the outbox store uses.

* **Serialisable transactions.** The base fake is optimistic and checks nothing about what a transaction read. Here a
  transaction records the version of every document it read, and its commit raises `Aborted` (the library retries the
  callable) if any of them was written since, as Firestore does. A store that is only safe under the emulator's read
  locks fails here, and two instances racing for one lease cannot both win.
* **Queries.** `where(filter=FieldFilter)` (equality), `order_by(field)`, `limit`, `stream()` over the documents of one
  collection (nested collections excluded).
* `attempted_paths` lists every path a read or write named, successful or not (the injection tests read it).

No network, no credentials, no I/O. It knows nothing about an outbox.
"""

from __future__ import annotations

import threading
from typing import Any

from _ppl11c_fs_fake import FakeFirestore, FakeQuery, FakeRef, FakeSnapshot, FakeTransaction
from google.api_core import exceptions as gexc


class OccRef(FakeRef):
    def get(self, transaction: Any = None, **kw: Any) -> FakeSnapshot:
        self._db.touched.append(self.path)
        with self._db.lock:
            snapshot = super().get(transaction=transaction, **kw)
            if transaction is not None:
                transaction.reads.setdefault(self.path, self._db.versions.get(self.path, 0))
        return snapshot


class OccQuery(FakeQuery):
    def __init__(self, db: OccFirestore, prefix: str, filters: tuple = (), order: str | None = None, cap=None) -> None:
        super().__init__(db, prefix, cap)
        self._filters, self._order = filters, order

    def limit(self, count: int) -> OccQuery:
        return OccQuery(self._db, self._prefix, self._filters, self._order, count)

    def order_by(self, field: str, **_: Any) -> OccQuery:
        return OccQuery(self._db, self._prefix, self._filters, field, self._limit)

    _after: str | None = None

    def start_after(self, values: dict) -> OccQuery:
        """A cursor on the document id (`{"__name__": id}`): the rows after it, in id order. Call it last."""
        query = OccQuery(self._db, self._prefix, self._filters, self._order, self._limit)
        query._after = self._prefix + next(iter(values.values()))
        return query

    def where(self, *, filter: Any) -> OccQuery:  # noqa: A002 - the library's keyword
        assert filter.op_string == "==", "the fake serves equality filters only"
        return OccQuery(
            self._db, self._prefix, (*self._filters, (filter.field_path, filter.value)), self._order, self._limit
        )

    def stream(self, transaction: Any = None, **_: Any) -> Any:
        self._db.touched.append(self._prefix)
        with self._db.lock:
            paths = [p for p in self._db.docs if p.startswith(self._prefix) and "/" not in p[len(self._prefix) :]]
            rows = [(p, self._db.read(p)) for p in paths]
        rows = [r for r in rows if all(r[1].to_dict().get(f) == v for f, v in self._filters)]
        rows.sort(key=lambda r: (r[1].to_dict().get(self._order), r[0]) if self._order else (0, r[0]))
        rows = [r for r in rows if self._after is None or r[0] > self._after]
        yield from (snap for _path, snap in rows[: self._limit])


class OccTransaction(FakeTransaction):
    def __init__(self, db: OccFirestore) -> None:
        super().__init__(db)
        self.reads: dict[str, int] = {}

    def _begin(self, retry_id: bytes | None = None) -> None:
        super()._begin(retry_id)
        self.reads = {}

    def _commit(self) -> list:
        db: OccFirestore = self._db
        with db.lock:
            for path, version in self.reads.items():
                if db.versions.get(path, 0) != version:
                    self._ops, self.reads, self._id = [], {}, None
                    raise gexc.Aborted("the documents read changed")
            ops, self._ops, self._id = self._ops, [], None
            db.commit(ops)
        return []

    def _write(self, kind: str, reference: Any, data: Any) -> None:
        self._db.touched.append(reference.path)
        self._ops.append((kind, reference.path, None if data is None else dict(data)))

    def create(self, reference: Any, document_data: Any) -> None:  # type: ignore[override]
        self._write("create", reference, document_data)

    def set(self, reference: Any, document_data: Any, merge: bool = False) -> None:  # type: ignore[override]
        self._write("set", reference, document_data)

    def update(self, reference: Any, field_updates: Any, option: Any = None) -> None:  # type: ignore[override]
        self._write("update", reference, field_updates)

    def delete(self, reference: Any, option: Any = None) -> None:  # type: ignore[override]
        self._write("delete", reference, None)


class OccFirestore(FakeFirestore):
    def __init__(self) -> None:
        super().__init__()
        self.lock = threading.RLock()
        self.versions: dict[str, int] = {}
        self.touched: list[str] = []
        self.committed_batches: list[list[str]] = []  # the paths of each atomic commit, in order

    def document(self, path: str) -> OccRef:
        return OccRef(self, path)

    def collection(self, path: str) -> OccQuery:
        return OccQuery(self, path.rstrip("/") + "/")

    def transaction(self, **_: Any) -> OccTransaction:
        return OccTransaction(self)

    def commit(self, ops: list) -> None:
        with self.lock:
            super().commit(ops)
            for _kind, path, _data in ops:
                self.versions[path] = self.versions.get(path, 0) + 1
            self.committed_batches.append([path for _k, path, _d in ops])
