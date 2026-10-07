"""tilo-api's durable store: a write-through cache over Firestore (PROD-WIRE, ADR-0026 decisions 2, 3 and 5).

`DurableStore` is a `deps.Store` whose plain dicts routes read as ever. Loads are lazy: by the ids of a request's path
(`load_path`) and by owner (`load_owner`, before any route iterates an owner's worlds or policies). A write is one
rev-checked backend transaction that holds the new records and the event parts (the world's durable queue); only then
does the cache change, and the queue drains through the single `EventWriter`, oldest first, resending by id: no record
without its events, no event twice. A failed or ambiguous commit evicts what it touched (503 `store_unavailable`; a
`rev` mismatch is 409 `stale`). `MemoryBackend` serves tests; `FirestoreBackend` is the same layout in Firestore, with
the parts as JSON strings and the layout as one, because Firestore refuses arrays of arrays.

A world whose stream has `world.started`, no terminal event, no run of this process and a free lease gets one
`world.failed` when this process loads it (decision 5), so it does not look busy forever.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import os
import re
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from tilo_planning.gaps import Gap
from tilo_planning.questions import Question

from tilo_api import deps, events, store_door

logger = logging.getLogger("tilo_api.durable_store")

_ID = {
    "worlds": re.compile(r"^w_[0-9A-Za-z_]{1,48}$"),
    "tasks": re.compile(r"^t_[0-7][0-9A-HJKMNP-TV-Z]{25}$"),
    "policies": re.compile(r"^pol_[0-9a-z_]{1,48}$"),
}
RESTARTED = "the service restarted, so the work stopped"


class StaleRev(Exception):
    """A record's `rev` is not the one the writer read, or a create found the record there."""


@contextmanager
def _io() -> Iterator[None]:
    """Any backend failure is 503 `store_unavailable`, never its text."""
    try:
        yield
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("api store failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="store_unavailable") from exc


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=dataclasses.asdict))


def _world_from(d: Mapping[str, Any]) -> deps.WorldRecord:
    districts = {k: deps.DistrictRecord(**v) if v else None for k, v in d["districts"].items()}
    return deps.WorldRecord(
        d["owner"], districts, tuple(d["owner_channels"]), d["run_id"], d["paused"], d["prior_world_id"], d["layout"]
    )


def _task_doc(t: deps.TaskRecord) -> dict[str, Any]:
    return _plain({f.name: getattr(t, f.name) for f in dataclasses.fields(t) if f.name != "lock"})


def _task_from(d: Mapping[str, Any]) -> deps.TaskRecord:
    asked = [
        Question(q["field"], q["text"], tuple(q["suggested_answers"]), q["expected_change"]) for q in d["questions"]
    ]
    t = deps.TaskRecord(d["owner"], d["world_id"], d["run_id"], d["draft"], d["brief"], asked, d["next_seq"])
    t.answers, t.edits, t.approaches, t.granted, t.scenario = (
        d[k] for k in ("answers", "edits", "approaches", "granted", "scenario")
    )
    t.gaps = tuple(Gap(**g) for g in d["gaps"])
    return t


def _fresh(cur: Mapping[str, Any] | None, expect: int | None) -> bool:
    """A create finds nothing there; an update finds the `rev` it read."""
    return cur is None if expect is None else cur is not None and cur["rev"] == expect


def _stored(coll: str, data: dict[str, Any], expect: int | None, cur: Mapping[str, Any] | None) -> dict[str, Any]:
    doc = {**data, "rev": (expect or 0) + 1}
    if coll != "policies":
        doc["created_at"] = cur["created_at"] if cur else events.now()
    return doc


class MemoryBackend:
    """The records and queues in a dict: the same semantics as Firestore, for the default test run."""

    def __init__(self) -> None:
        self.docs: dict[tuple[str, str], dict[str, Any]] = {}
        self.queues: dict[str, list[dict[str, Any]]] = {}
        self.lock = threading.RLock()

    def read(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.docs.get((collection, doc_id)))

    def queue(self, world_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.queues.get(world_id, []))

    def find(self, collection: str, field: str, value: Any) -> list[tuple[str, dict[str, Any]]]:
        def get(doc: Any) -> Any:
            for key in field.split("."):
                doc = doc.get(key) if isinstance(doc, dict) else None
            return doc

        return [(i, self.read(c, i)) for (c, i), d in list(self.docs.items()) if c == collection and get(d) == value]  # type: ignore[misc]

    def commit(self, writes: list[tuple[str, str, dict[str, Any], int | None]], appends: dict[str, list[dict]]) -> None:
        with self.lock:
            for coll, i, _, expect in writes:
                cur = self.docs.get((coll, i))
                if not _fresh(cur, expect):
                    raise StaleRev
            for coll, i, data, expect in writes:
                self.docs[(coll, i)] = _plain(_stored(coll, data, expect, self.docs.get((coll, i))))
            for w, parts in appends.items():
                queued = self.queues.setdefault(w, [])
                queued += [_plain(p) for p in parts if p["id"] not in {q["id"] for q in queued}]

    def ack(self, world_id: str, part_id: str) -> None:
        with self.lock:
            self.queues[world_id] = [p for p in self.queues.get(world_id, []) if p["id"] != part_id]


class FirestoreBackend:
    """`orgs/{org}/worlds|tasks|policies/{id}` and `worlds/{world}/_pending/queue` over one client (ADR-0026)."""

    def __init__(self, client: Any, *, org_id: str = deps.ORG_ID) -> None:
        self.client, self.org_id = client, org_id

    def _ref(self, path: str) -> Any:
        return self.client.document(f"orgs/{self.org_id}/{path}")

    @staticmethod
    def _dec(doc: dict[str, Any]) -> dict[str, Any]:
        layout = doc.get("layout")
        return {**doc, "layout": json.loads(layout)} if isinstance(layout, str) else doc

    def read(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        doc = self._ref(f"{collection}/{doc_id}").get().to_dict()
        return None if doc is None else self._dec(doc)

    def queue(self, world_id: str) -> list[dict[str, Any]]:
        doc = self._ref(f"worlds/{world_id}/_pending/queue").get().to_dict() or {}
        return [json.loads(p) for p in doc.get("parts", [])]

    def find(self, collection: str, field: str, value: Any) -> list[tuple[str, dict[str, Any]]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection(f"orgs/{self.org_id}/{collection}").where(filter=FieldFilter(field, "==", value))
        return [(d.id, self._dec(d.to_dict())) for d in query.stream()]

    def commit(self, writes: list[tuple[str, str, dict[str, Any], int | None]], appends: dict[str, list[dict]]) -> None:
        from google.cloud import firestore

        @firestore.transactional  # type: ignore[misc]
        def run(tx: Any) -> None:
            held = [(self._ref(f"{c}/{i}"), c, d, e) for c, i, d, e in writes]
            current = [ref.get(transaction=tx).to_dict() for ref, *_ in held]
            queues = {w: self._ref(f"worlds/{w}/_pending/queue") for w in appends}
            queued = {w: (ref.get(transaction=tx).to_dict() or {}).get("parts", []) for w, ref in queues.items()}
            if not all(_fresh(cur, e) for (_, _, _, e), cur in zip(held, current, strict=True)):
                raise StaleRev
            for (ref, coll, data, expect), cur in zip(held, current, strict=True):
                doc = _stored(coll, data, expect, cur)
                tx.set(
                    ref,
                    {**doc, "layout": json.dumps(doc["layout"]) if doc.get("layout") is not None else None}
                    if coll == "worlds"
                    else doc,
                )
            for w, parts in appends.items():
                seen = {json.loads(p)["id"] for p in queued[w]}
                new = [json.dumps(p, sort_keys=True) for p in parts if p["id"] not in seen]
                tx.set(queues[w], {"parts": [*queued[w], *new]})

        run(self.client.transaction())

    def ack(self, world_id: str, part_id: str) -> None:
        from google.cloud import firestore

        ref = self._ref(f"worlds/{world_id}/_pending/queue")

        @firestore.transactional  # type: ignore[misc]
        def run(tx: Any) -> None:
            parts = (ref.get(transaction=tx).to_dict() or {}).get("parts", [])
            tx.set(ref, {"parts": [p for p in parts if json.loads(p)["id"] != part_id]})

        run(self.client.transaction())


class DurableStore(deps.Store):
    def __init__(self, backend: Any, events_backend: Any, *, org_id: str = deps.ORG_ID) -> None:
        super().__init__()
        self.backend, self.events_backend, self.org_id = backend, events_backend, org_id
        self.writer: deps.EventWriter | None = (
            None  # the loads drain, and write the restart's `world.failed`, through it
        )
        self.revs: dict[tuple[str, str], int] = {}
        self._owners: set[str] = set()
        self._lock = threading.RLock()

    # -- loads: a miss is never cached, and an id that is not its schema's never reaches the backend
    def _doc(self, coll: str, doc_id: Any) -> dict[str, Any] | None:
        if not isinstance(doc_id, str) or not _ID[coll].match(doc_id):
            return None
        with _io():
            return self.backend.read(coll, doc_id)

    def _adopt_world(self, w: str, d: Mapping[str, Any]) -> bool:
        with self._lock, _io():
            if w in self.worlds:
                return False
            self.events[w] = self.events_backend.read_events(self.org_id, w)
            self.pending_events[w] = self.backend.queue(w)
            self.revs[("worlds", w)], self.worlds[w] = d["rev"], _world_from(d)
            return True

    def _adopt_policy(self, p: str, d: Mapping[str, Any]) -> None:
        with self._lock:
            if p not in self.policies:
                self.revs[("policies", p)], self.policies[p], self.policy_worlds[p] = (
                    d["rev"],
                    d["record"],
                    d["world_id"],
                )
        if d["world_id"]:
            self.load_world(d["world_id"])

    def _settle(self, w: str) -> None:
        """What the previous process left: its queue is sent, and a started world with no end and no run is closed."""
        if self.writer is None:
            return
        try:
            self.drain(w)
            stream, record = self.events.get(w, []), self.worlds[w]
            types = {e["type"] for e in stream}
            if (
                "world.started" in types
                and not types & {"world.completed", "world.failed"}
                and not (record.paused or w in self.runs)
            ):
                self.writer.append(w, events.world_failed_part(w, RESTARTED))
        except Exception as exc:  # a busy lease belongs to whoever holds it; the next process looks again
            logger.warning("settling world %s failed (%s)", w, type(exc).__name__)

    def load_world(self, world_id: str) -> deps.WorldRecord | None:
        if (
            world_id not in self.worlds
            and (d := self._doc("worlds", world_id)) is not None
            and self._adopt_world(world_id, d)
        ):
            self._settle(world_id)
        return self.worlds.get(world_id)

    def load_task(self, task_id: str) -> deps.TaskRecord | None:
        if task_id not in self.tasks and (d := self._doc("tasks", task_id)) is not None:
            with self._lock:
                self.revs[("tasks", task_id)], self.tasks[task_id] = d["rev"], _task_from(d)
        task = self.tasks.get(task_id)
        if task is not None:
            self.load_world(task.world_id)
        return task

    def load_owner(self, owner: str) -> None:
        if owner in self._owners:
            return
        with _io():
            worlds, policies = (
                self.backend.find("worlds", "owner", owner),
                self.backend.find("policies", "record.owner", owner),
            )
        fresh = [w for w, d in worlds if self._adopt_world(w, d)]
        for p, d in policies:
            self._adopt_policy(p, d)
        for w in fresh:
            self._settle(w)
        self._owners.add(owner)

    def load_path(self, params: Mapping[str, Any]) -> DurableStore:
        self.load_world(params.get("world_id"))  # type: ignore[arg-type]
        self.load_task(params.get("task_id"))  # type: ignore[arg-type]
        p = params.get("policy_id")
        if isinstance(p, str) and p not in self.policies and (d := self._doc("policies", p)) is not None:
            self._adopt_policy(p, d)
        return self

    # -- writes
    def commit(
        self,
        *,
        worlds: Mapping[str, deps.WorldRecord] | None = None,
        tasks: Mapping[str, deps.TaskRecord] | None = None,
        policies: Mapping[str, dict] | None = None,
        policy_worlds: Mapping[str, str] | None = None,
        parts: Mapping[str, list[dict]] | None = None,
        create: Iterable[tuple[str, str]] = (),
        evict: bool = True,
    ) -> None:
        made, parts = set(create), {w: list(p) for w, p in (parts or {}).items() if p}
        with self._lock:
            mapped = {p: (policy_worlds or {}).get(p, self.policy_worlds.get(p)) for p in policies or {}}
            records = [("worlds", i, _plain(r)) for i, r in (worlds or {}).items()]
            records += [("tasks", i, _task_doc(r)) for i, r in (tasks or {}).items()]
            records += [
                ("policies", i, {"record": _plain(r), "world_id": mapped[i]}) for i, r in (policies or {}).items()
            ]
            touched = [(c, i) for c, i, _ in records]
            try:
                writes = [(c, i, d, self._expect(c, i, (c, i) in made, not evict)) for c, i, d in records]
                self.backend.commit(writes, parts)
            except Exception as exc:
                self._evict(touched, parts, forget=evict)
                if isinstance(exc, StaleRev):
                    raise HTTPException(status_code=409, detail="stale") from None
                logger.warning("api store commit failed (%s)", type(exc).__name__)
                raise HTTPException(status_code=503, detail="store_unavailable") from exc
            for c, i, _, expect in writes:
                self.revs[(c, i)] = (expect or 0) + 1
            self.worlds.update(worlds or {})
            self.tasks.update(tasks or {})
            self.policies.update(policies or {})
            self.policy_worlds.update({p: w for p, w in mapped.items() if w})
            for w, new in parts.items():
                queued = self.pending_events.get(w, [])
                self.pending_events[w] = [*queued, *(p for p in new if p["id"] not in {q["id"] for q in queued})]

    def _expect(self, coll: str, doc_id: str, creating: bool, authoritative: bool) -> int | None:
        """The `rev` a write must find: none for a create. An in-place change (a kill switch, the layout) is
        authoritative here, so a `rev` that a failed commit made unknown is read again rather than refused."""
        if creating:
            return None
        if (coll, doc_id) in self.revs or not authoritative:
            return self.revs.get((coll, doc_id))
        doc = self.backend.read(coll, doc_id)
        return None if doc is None else doc["rev"]

    def _evict(self, touched: list[tuple[str, str]], parts: Mapping[str, Any], *, forget: bool) -> None:
        """After a failed commit the `rev` of what it touched is unknown. `forget` also drops the cached entries, so the
        next access reloads what is really stored; a kill switch's in-place change stays."""
        cached: dict[str, dict[str, Any]] = {"worlds": self.worlds, "tasks": self.tasks, "policies": self.policies}
        for coll, i in touched:
            self.revs.pop((coll, i), None)
            if forget:
                cached[coll].pop(i, None)
                if coll == "worlds":
                    self.events.pop(i, None)
                    self.pending_events.pop(i, None)
        if forget:
            self._owners.clear()  # an evicted world is found again by the next `load_owner`
            for w in parts:
                self.pending_events.pop(w, None)

    def ack(self, world_id: str, part_id: str) -> None:
        """The part is committed: out of the durable queue and the cache. A failed ack only means a resend by id."""
        try:
            self.backend.ack(world_id, part_id)
        except Exception as exc:
            logger.warning("ack of a queued event failed (%s)", type(exc).__name__)
            return
        self.pending_events[world_id] = [p for p in self.pending_events.get(world_id, []) if p["id"] != part_id]

    def drain(self, world_id: str, writer: deps.EventWriter | None = None) -> None:
        """Appends the queued parts oldest first through `writer`; the first failure stops it and the rest stay."""
        writer = writer or self.writer
        for part in list(self.pending_events.get(world_id, [])):
            try:
                assert writer is not None
                writer.append(world_id, part)
            except Exception as exc:
                raise deps.event_failure(world_id, exc) from None
            self.ack(world_id, part["id"])

    def save(
        self, writer: deps.EventWriter | None, *, parts: Mapping[str, list[dict]] | None = None, **records: Any
    ) -> None:
        self.commit(parts=parts, **records)
        for w in parts or {}:
            self.drain(w, writer)


# -- the deployed seams: one store and one adapter per config, sharing one client
_opened: dict[tuple[str | None, ...], tuple[DurableStore, deps.EventWriter]] = {}
_opening = threading.Lock()
_CONFIG = (store_door.ENV_STORE, store_door.ENV_PROJECT, "FIRESTORE_EMULATOR_HOST", "GOOGLE_CLOUD_PROJECT", "K_SERVICE")


def deployed() -> tuple[DurableStore, deps.EventWriter]:
    """The cached store and writer for this config, or 503: `not_configured` (never cached) or `store_unavailable`."""
    from tilo_api.world_writer import WorldWriterAdapter

    key = tuple(os.environ.get(name) for name in _CONFIG)
    with _opening:
        if key not in _opened:
            try:
                opened = store_door.open_api_store(firestore_client_factory=store_door.client_factory)
            except store_door.ApiStoreNotConfigured:
                raise HTTPException(status_code=503, detail="not_configured") from None
            store = DurableStore(opened.records, opened.events)
            store.writer = WorldWriterAdapter(store, opened.events)
            _opened[key] = (store, store.writer)
        return _opened[key]


def close_deployed() -> None:
    """On shutdown (SIGTERM): every writer closes and releases its lease, so a new revision does not wait it out."""
    for _, writer in list(_opened.values()):
        getattr(writer, "reopen", lambda: None)()
