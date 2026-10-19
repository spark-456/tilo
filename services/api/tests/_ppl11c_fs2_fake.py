"""An in-memory stand-in for the Firestore client for the PPL-11c-FS-2 tests (API_PPL_11c_FS_2.md section 0).

Unlike `_ppl11c_fs_fake` (optimistic, no read checks: it exists to catch a store whose uniqueness rests on lock
behaviour), this one models what a limiter or an idempotency store may rely on, and nothing more:

* **Serializable transactions.** A transaction records the version of every document and the result set of every
  query it read; at commit, a document or a result set that changed since is `Aborted`, which
  `firestore.transactional` retries (up to its own five attempts) exactly as it does against the server. A
  read-modify-write outside a transaction gets no such protection, which is what the racing tests catch.
* **Preconditions.** `write_option(last_update_time=snapshot.update_time)` and `write_option(exists=...)` are enforced
  (`FailedPrecondition` / `NotFound` / `AlreadyExists`), on a direct write and inside a transaction.
* **Field transforms.** `Increment`, `ArrayUnion`, `ArrayRemove`, `SERVER_TIMESTAMP` and `DELETE_FIELD`, dotted
  `update` paths, `set(merge=True)`. A naive `datetime` is stored as UTC and read back aware, as Firestore does (a
  Timestamp); an ISO string stays a string (so a TTL policy on that field would never fire).
* **Queries.** `where` (`==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `array_contains`; `FieldFilter` or the legacy three
  arguments), `order_by`, `limit`, `stream`, `get`, collection groups, `batch()`, `recursive_delete`.

Test levers (not Firestore API):

* `outage`: a callable `path -> bool` (or `True`): any read or write that touches such a path raises
  `ServiceUnavailable` carrying `SENTINEL` in its text, before anything is applied.
* `arm_fault(nth, applied=)`: the `nth` counted operation (a read, a query or a commit that touches a non-record path,
  counted from 1) raises `DeadlineExceeded` (with `SENTINEL`); with `applied=True` a commit lands first (a lost
  answer), so the caller does not know whether it happened. `fault_fired`, `disarm()`.
* `limiter_docs()`: every document that is not a people record (the counters and idempotency records of FS-2);
  `record_writes()`: the writes that touched a people record collection; `attempted_ops` as in `_ppl11c_fs_fake`.

No network, no credentials, no I/O, no logging. Nothing here knows what a counter, a key or a person is.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud.firestore_v1 import ReadAfterWriteError, transforms
from google.cloud.firestore_v1.base_transaction import BaseTransaction
from google.cloud.firestore_v1.transaction import Transaction

SENTINEL = "SENTINEL-d2c80b7e-store-text"  # text no response body, log line or document of the limiter may carry

RECORD_COLLECTIONS = frozenset(
    {
        "people_person",
        "people_meeting",
        "people_work_item",
        "people_pinboard_item",
        "people_mention",
        "people_calendar_entry",
        "people_directory",
    }
)
_WRITE_KINDS = ("create", "set", "merge", "update", "delete")


def is_record_path(path: str) -> bool:
    """`orgs/{org}/people_{kind}/...` or `orgs/{org}/people_directory/...`: the people record stores (FS-1)."""
    parts = path.split("/")
    return len(parts) >= 3 and parts[0] == "orgs" and parts[2] in RECORD_COLLECTIONS


def _utc(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value


def _dig(data: Any, field_path: str) -> Any:
    current = data
    for part in field_path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return _MISSING
        current = current[part]
    return current


class _Missing:
    def __repr__(self) -> str:
        return "<missing>"


_MISSING = _Missing()


class Option:
    """What `client.write_option(...)` returns: a precondition."""

    def __init__(self, last_update_time: Any = None, exists: bool | None = None) -> None:
        self.last_update_time, self.exists = last_update_time, exists


class Snap:
    def __init__(self, db: FakeFirestore2, path: str, data: Mapping[str, Any] | None, version: int) -> None:
        self._db, self.id, self.reference_path = db, path.rsplit("/", 1)[-1], path
        self._data = None if data is None else copy.deepcopy(dict(data))
        self.update_time = version
        self.create_time = version

    @property
    def exists(self) -> bool:
        return self._data is not None

    @property
    def reference(self) -> Ref:
        return Ref(self._db, self.reference_path)

    def to_dict(self) -> dict[str, Any] | None:
        return None if self._data is None else copy.deepcopy(self._data)

    def get(self, field_path: str) -> Any:
        found = _dig(self._data, field_path) if self._data is not None else _MISSING
        if found is _MISSING:
            raise KeyError(field_path)
        return copy.deepcopy(found)


class Ref:
    def __init__(self, db: FakeFirestore2, path: str) -> None:
        self._db, self.path, self.id = db, path, path.rsplit("/", 1)[-1]

    def get(self, transaction: Any = None, **_: Any) -> Snap:
        _refuse_read_after_write(transaction)
        return self._db.read(self.path, transaction)

    def create(self, data: Mapping[str, Any]) -> None:
        self._db.commit([("create", self.path, dict(data), None)])

    def set(self, data: Mapping[str, Any], merge: bool = False) -> None:
        self._db.commit([("merge" if merge else "set", self.path, dict(data), None)])

    def update(self, data: Mapping[str, Any], option: Any = None) -> None:
        self._db.commit([("update", self.path, dict(data), option)])

    def delete(self, option: Any = None) -> None:
        self._db.commit([("delete", self.path, None, option)])

    def collection(self, name: str) -> Query:
        return Query(self._db, f"{self.path}/{name}/")


def _refuse_read_after_write(transaction: Any) -> None:
    if transaction is not None and getattr(transaction, "_ops", None):
        raise ReadAfterWriteError("Attempted read after write in a transaction.")


class Query:
    def __init__(
        self,
        db: FakeFirestore2,
        prefix: str,
        filters: tuple[tuple[str, str, Any], ...] = (),
        order: tuple[tuple[str, bool], ...] = (),
        count: int | None = None,
        group: str | None = None,
    ) -> None:
        self._db, self._prefix, self._filters, self._order, self._limit, self._group = (
            db,
            prefix,
            filters,
            order,
            count,
            group,
        )

    def _with(self, **kw: Any) -> Query:
        state = dict(
            db=self._db,
            prefix=self._prefix,
            filters=self._filters,
            order=self._order,
            count=self._limit,
            group=self._group,
        )
        state.update(kw)
        return Query(**state)

    def where(
        self, field_path: str | None = None, op_string: str | None = None, value: Any = None, *, filter: Any = None
    ) -> Query:  # noqa: A002
        if filter is not None:
            field_path, op_string, value = filter.field_path, filter.op_string, filter.value
        assert field_path is not None and op_string is not None
        return self._with(filters=(*self._filters, (field_path, op_string, _utc(value))))

    def order_by(self, field_path: str, direction: str | None = None) -> Query:
        return self._with(order=(*self._order, (field_path, str(direction or "ASCENDING").upper() == "DESCENDING")))

    def limit(self, count: int) -> Query:
        return self._with(count=count)

    def _matches(self, data: Mapping[str, Any]) -> bool:
        for field_path, op, want in self._filters:
            have = _dig(data, field_path)
            if have is _MISSING:
                return False
            ok = {
                "==": lambda: have == want,
                "!=": lambda: have != want,
                "<": lambda: have < want,
                "<=": lambda: have <= want,
                ">": lambda: have > want,
                ">=": lambda: have >= want,
                "in": lambda: have in want,
                "array_contains": lambda: want in have,
            }[op]()
            if not ok:
                return False
        return True

    def _paths(self) -> list[str]:
        """The matching paths now, in query order (caller holds the database lock)."""
        db = self._db
        if self._group is not None:
            found = [p for p in db.docs if len(p.split("/")) >= 2 and p.split("/")[-2] == self._group]
        else:
            found = [p for p in db.docs if p.startswith(self._prefix) and "/" not in p[len(self._prefix) :]]
        found = [p for p in found if self._matches(db.docs[p])]
        found.sort()
        for field_path, descending in reversed(self._order):
            found.sort(key=lambda p: _sortable(_dig(db.docs[p], field_path)), reverse=descending)
        return found[: self._limit]

    def stream(self, transaction: Any = None, **_: Any) -> Any:
        _refuse_read_after_write(transaction)
        return iter(self._db.read_query(self, transaction))

    def get(self, transaction: Any = None, **_: Any) -> list[Snap]:
        return list(self.stream(transaction=transaction))

    def _signature(self) -> list[tuple[str, int]]:
        return [(p, self._db.version(p)) for p in self._paths()]


def _sortable(value: Any) -> Any:
    return (1, 0) if value is _MISSING else (0, value)


class Tx(Transaction):
    """A real `Transaction` with the network taken out; reads are validated at commit (serializable)."""

    def __init__(self, db: FakeFirestore2, max_attempts: int = 5, read_only: bool = False) -> None:
        BaseTransaction.__init__(self, max_attempts, read_only)
        self._db = db
        self._ops: list[tuple[str, str, Any, Any]] = []
        self._reads: dict[str, int] = {}
        self._queries: list[Query] = []
        self._signatures: list[list[tuple[str, int]]] = []

    def _clean_up(self) -> None:
        self._id = None
        self._ops, self._reads, self._queries, self._signatures = [], {}, [], []

    def _begin(self, retry_id: bytes | None = None) -> None:
        self._clean_up()
        self._id = b"fake-transaction"

    def _commit(self) -> list:
        ops, reads, signatures = self._ops, self._reads, list(zip(self._queries, self._signatures, strict=True))
        self._clean_up()
        self._db.commit(ops, reads=reads, queries=signatures)
        return []

    def _rollback(self) -> None:
        self._clean_up()

    def create(self, reference: Ref, document_data: Mapping[str, Any]) -> None:  # type: ignore[override]
        self._ops.append(("create", reference.path, dict(document_data), None))

    def set(self, reference: Ref, document_data: Mapping[str, Any], merge: bool = False) -> None:  # type: ignore[override]
        self._ops.append(("merge" if merge else "set", reference.path, dict(document_data), None))

    def update(self, reference: Ref, field_updates: Mapping[str, Any], option: Any = None) -> None:  # type: ignore[override]
        self._ops.append(("update", reference.path, dict(field_updates), option))

    def delete(self, reference: Ref, option: Any = None) -> None:  # type: ignore[override]
        self._ops.append(("delete", reference.path, None, option))

    def get(self, ref_or_query: Any, **_: Any) -> Any:  # type: ignore[override]
        if isinstance(ref_or_query, Ref):
            return iter([ref_or_query.get(transaction=self)])
        return ref_or_query.stream(transaction=self)

    def get_all(self, references: Any, **_: Any) -> Any:  # type: ignore[override]
        return (ref.get(transaction=self) for ref in references)


class Batch:
    def __init__(self, db: FakeFirestore2) -> None:
        self._db, self._ops = db, []

    def create(self, reference: Ref, data: Mapping[str, Any]) -> None:
        self._ops.append(("create", reference.path, dict(data), None))

    def set(self, reference: Ref, data: Mapping[str, Any], merge: bool = False) -> None:
        self._ops.append(("merge" if merge else "set", reference.path, dict(data), None))

    def update(self, reference: Ref, data: Mapping[str, Any], option: Any = None) -> None:
        self._ops.append(("update", reference.path, dict(data), option))

    def delete(self, reference: Ref, option: Any = None) -> None:
        self._ops.append(("delete", reference.path, None, option))

    def commit(self) -> list:
        ops, self._ops = self._ops, []
        self._db.commit(ops)
        return []


class FakeFirestore2:
    """The client. One re-entrant lock makes every read and every commit atomic, as the server does."""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.attempted_ops: list[tuple[str, str]] = []
        self.log: list[tuple[str, str]] = []  # every counted operation: (kind, path or prefix)
        self.outage: Callable[[str], bool] | bool | None = None
        self.server_now: Callable[[], datetime] = lambda: datetime.now(UTC)
        self._versions: dict[str, int] = {}
        self._counter = 0
        self._lock = threading.RLock()
        self._fault: dict[str, Any] | None = None
        self.fault_fired = False
        self.counted = 0

    # -- the client surface ------------------------------------------------------------------------------------------
    def document(self, path: str) -> Ref:
        return Ref(self, path)

    def collection(self, path: str) -> Query:
        return Query(self, path.rstrip("/") + "/")

    def collection_group(self, collection_id: str) -> Query:
        return Query(self, "", group=collection_id)

    def transaction(self, **_: Any) -> Tx:
        return Tx(self)

    def batch(self) -> Batch:
        return Batch(self)

    def write_option(self, **kw: Any) -> Option:
        return Option(kw.get("last_update_time"), kw.get("exists"))

    def get_all(self, references: Any, transaction: Any = None, **_: Any) -> Any:
        return (ref.get(transaction=transaction) for ref in references)

    def recursive_delete(self, reference: Any, **_: Any) -> int:
        path = reference.path if isinstance(reference, Ref) else str(reference).rstrip("/")
        with self._lock:
            doomed = [p for p in self.docs if p == path or p.startswith(path + "/")]
            self.commit([("delete", p, None, None) for p in doomed])
            return len(doomed)

    # -- levers ------------------------------------------------------------------------------------------------------
    def arm_fault(self, nth: int, *, applied: bool = False) -> None:
        self._fault = {"nth": nth, "applied": applied, "seen": 0}
        self.fault_fired = False

    def disarm(self) -> None:
        self._fault = None

    def limiter_docs(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {p: copy.deepcopy(d) for p, d in self.docs.items() if not is_record_path(p)}

    def record_writes(self) -> list[tuple[str, str]]:
        return [(k, p) for k, p in self.attempted_ops if is_record_path(p) and k in _WRITE_KINDS]

    def raw(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            found = self.docs.get(path)
            return None if found is None else copy.deepcopy(found)

    def put(self, path: str, doc: Mapping[str, Any]) -> None:
        with self._lock:
            self.docs[path] = copy.deepcopy(dict(doc))
            self._versions[path] = self._versions.get(path, 0) + 1

    def version(self, path: str) -> int:
        return self._versions.get(path, 0) if path in self.docs else 0

    # -- operations --------------------------------------------------------------------------------------------------
    def _gate(self, kind: str, paths: list[str]) -> bool:
        """Outage and fault injection for one operation. True when a commit must land and then fail (a lost answer)."""
        outage = self.outage
        if outage is not None and any(outage is True or outage(p) for p in paths):
            raise gexc.ServiceUnavailable(f"503 the service is unavailable {SENTINEL}")
        if all(is_record_path(p) for p in paths):
            return False
        self.counted += 1
        self.log.append((kind, paths[0]))
        fault = self._fault
        if fault is None or self.fault_fired:
            return False
        fault["seen"] += 1
        if fault["seen"] != fault["nth"]:
            return False
        self.fault_fired = True
        if kind == "commit" and fault["applied"]:
            return True
        raise gexc.DeadlineExceeded(f"504 deadline exceeded {SENTINEL}")

    def read(self, path: str, transaction: Any = None) -> Snap:
        with self._lock:
            self._gate("read", [path])
            snap = Snap(self, path, self.docs.get(path), self.version(path))
            if transaction is not None:
                transaction._reads.setdefault(path, self.version(path))
            return snap

    def read_query(self, query: Query, transaction: Any = None) -> list[Snap]:
        with self._lock:
            self._gate("query", [query._prefix or f"group:{query._group}/x"])
            paths = query._paths()
            snaps = [Snap(self, p, self.docs[p], self.version(p)) for p in paths]
            if transaction is not None:
                transaction._queries.append(query)
                transaction._signatures.append(query._signature())
                for p in paths:
                    transaction._reads.setdefault(p, self.version(p))
            return snaps

    def commit(
        self,
        ops: list[tuple[str, str, Any, Any]],
        reads: Mapping[str, int] | None = None,
        queries: list[tuple[Query, list[tuple[str, int]]]] | None = None,
    ) -> None:
        """All or nothing: a read that moved aborts (contention), each write has Firestore's precondition."""
        with self._lock:
            land_then_fail = self._gate("commit", [p for _, p, _, _ in ops])
            self.attempted_ops.extend((kind, path) for kind, path, _, _ in ops)
            for path, version in (reads or {}).items():
                if self.version(path) != version:
                    raise gexc.Aborted("409 the transaction was aborted: documents it read changed")
            for query, seen in queries or []:
                if query._signature() != seen:
                    raise gexc.Aborted("409 the transaction was aborted: a result set it read changed")
            staged = copy.deepcopy(self.docs)
            versions = dict(self._versions)
            for kind, path, data, option in ops:
                where = f"projects/p/databases/(default)/documents/{path}"
                present = path in staged
                if option is not None:
                    if option.exists is True and not present:
                        raise gexc.NotFound(f"No document to update: {where}")
                    if option.exists is False and present:
                        raise gexc.AlreadyExists(f"Document already exists: {where}")
                    if option.last_update_time is not None:
                        if not present:
                            raise gexc.NotFound(f"No document to update: {where}")
                        if option.last_update_time != versions.get(path, 0):
                            raise gexc.FailedPrecondition(f"the document changed: {where}")
                if kind == "create":
                    if present:
                        raise gexc.AlreadyExists(f"Document already exists: {where}")
                    staged[path] = self._build({}, data, dotted=False)
                elif kind == "set":
                    staged[path] = self._build({}, data, dotted=False)
                elif kind == "merge":
                    staged[path] = self._merge(staged.get(path, {}), data)
                elif kind == "update":
                    if not present:
                        raise gexc.NotFound(f"No document to update: {where}")
                    staged[path] = self._build(staged[path], data, dotted=True)
                else:
                    staged.pop(path, None)
                    versions.pop(path, None)
                    continue
                self._counter += 1
                versions[path] = self._counter
            self.docs, self._versions = staged, versions
            if land_then_fail:
                raise gexc.DeadlineExceeded(f"504 deadline exceeded after the write landed {SENTINEL}")

    # -- applying a write --------------------------------------------------------------------------------------------
    def _resolve(self, current: Any, value: Any) -> Any:
        if isinstance(value, transforms.Increment):
            return (current if isinstance(current, (int, float)) else 0) + value.value
        if isinstance(value, transforms.ArrayUnion):
            held = list(current) if isinstance(current, list) else []
            return held + [v for v in value.values if v not in held]
        if isinstance(value, transforms.ArrayRemove):
            held = list(current) if isinstance(current, list) else []
            return [v for v in held if v not in value.values]
        if value is transforms.SERVER_TIMESTAMP:
            return _utc(self.server_now())
        if isinstance(value, dict):
            base = current if isinstance(current, dict) else {}
            return {
                k: r for k, v in value.items() if (r := self._resolve(base.get(k), v)) is not transforms.DELETE_FIELD
            }
        return copy.deepcopy(_utc(value))

    def _build(self, base: dict[str, Any], data: Mapping[str, Any], *, dotted: bool) -> dict[str, Any]:
        out = copy.deepcopy(base)
        for key, value in data.items():
            parts = key.split(".") if dotted else [key]
            node = out
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            resolved = self._resolve(node.get(parts[-1]), value)
            if resolved is transforms.DELETE_FIELD:
                node.pop(parts[-1], None)
            else:
                node[parts[-1]] = resolved
        return out

    def _merge(self, base: dict[str, Any], data: Mapping[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(base)
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = self._merge(out[key], value)
            else:
                resolved = self._resolve(out.get(key), value)
                if resolved is transforms.DELETE_FIELD:
                    out.pop(key, None)
                else:
                    out[key] = resolved
        return out
