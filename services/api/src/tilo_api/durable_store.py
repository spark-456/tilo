"""tilo-api's durable store: a write-through cache over Firestore (PROD-WIRE, ADR-0026 decisions 2, 3 and 5).

`DurableStore` is a `deps.Store` whose plain dicts routes read as ever. Loads are lazy: by the ids of a request's path
(`load_path`, read-only: it runs before the route's own checks) and by owner (`load_owner`, before any route iterates
an owner's worlds or policies). A write is one rev-checked backend transaction that holds the new records and the event
parts (the world's durable queue); only then does the cache change, and the queue drains through the single
`EventWriter`, oldest first, resending by id: no record without its events, no event twice. A failed or ambiguous
commit evicts what it touched (503 `store_unavailable`; a `rev` mismatch is 409 `stale`). `MemoryBackend` serves
tests; `FirestoreBackend` is the same layout in Firestore, with the parts, the layout and the brief's free-form fields
as JSON strings, because Firestore refuses arrays of arrays.

`settle(world_id)` sends what a previous process left queued, and a world whose stream has `world.started`, no
terminal event, no run of this process and a free lease gets one `world.failed` (decision 5), so it does not look busy
forever. It writes, so a route calls it only after its own ownership check; `load_world`, `load_task` and
`load_owner` settle by default for callers that have checked, and `settle=False` is for those that have not.
At API startup, `recover_deployed` also visits the durable worlds before requests are served (X-ORPHAN-1 / HR-1).
It preserves paused runs and active leases; an unavailable store retains the normal route-level 503 behavior.

Kill switches (FR-HIL-07) change the cache in place first. `unsaved` keeps every such policy and world until a commit
lands, and `commit_unsaved` writes them all, so a retry that finds nothing new to lower still saves what is pending.
`deadline(s)` bounds the process-wide lock wait of the calling thread: a kill switch never waits behind another
commit's Firestore I/O (which holds the lock so `rev`s stay in order) for more than its budget.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from tilo_planning.gaps import Gap
from tilo_planning.questions import Question
from tilo_providers.diagnostics import log_caught

from tilo_api import deps, events, store_door

logger = logging.getLogger("tilo_api.durable_store")

_ID = {
    "worlds": re.compile(r"w_[0-9A-Za-z_]{1,48}"),
    "tasks": re.compile(r"t_[0-7][0-9A-HJKMNP-TV-Z]{25}"),
    "policies": re.compile(r"pol_[0-9a-z_]{1,48}"),
}
_JSON_FIELDS = {"worlds": ("layout",), "tasks": ("draft", "brief", "edits", "approaches", "maker_picks")}
RESTARTED = "the service restarted, so the work stopped"
STARTUP_RESTARTED = "Tilo restarted during this run; start it again"  # X-ORPHAN-1 / HR-1
_CLOSE_BUDGET_S = 5.0  # shutdown, well under Cloud Run's 10 s SIGTERM grace


class StaleRev(Exception):
    """A record's `rev` is not the one the writer read, or a create found the record there."""


def _valid(coll: str, doc_id: Any) -> bool:
    return isinstance(doc_id, str) and _ID[coll].fullmatch(doc_id) is not None


def _check(coll: str, doc_id: str) -> None:
    """Every id that becomes a path or a key is its schema's first (no `/`, no trailing newline)."""
    if not _valid(coll, doc_id):
        raise ValueError(f"{coll} id {doc_id!r} does not match its schema")


@contextmanager
def _io() -> Iterator[None]:
    """Any backend or decoding failure is 503 `store_unavailable`, never its text."""
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
    return _plain(
        {f.name: getattr(t, f.name) for f in dataclasses.fields(t) if f.name not in {"lock", "approaches_work"}}
    )


def _task_from(d: Mapping[str, Any]) -> deps.TaskRecord:
    asked = [
        Question(q["field"], q["text"], tuple(q["suggested_answers"]), q["expected_change"], q.get("label"))
        for q in d["questions"]
    ]
    t = deps.TaskRecord(d["owner"], d["world_id"], d["run_id"], d["draft"], d["brief"], asked, d["next_seq"])
    t.answers, t.edits, t.approaches, t.granted, t.scenario = (
        d[k] for k in ("answers", "edits", "approaches", "granted", "scenario")
    )
    t.maker_picks = d.get("maker_picks", [])
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
        _check(collection, doc_id)
        return copy.deepcopy(self.docs.get((collection, doc_id)))

    def world_ids(self) -> Iterator[str]:
        yield from (i for c, i in list(self.docs) if c == "worlds")

    def queue(self, world_id: str) -> list[dict[str, Any]]:
        _check("worlds", world_id)
        return copy.deepcopy(self.queues.get(world_id, []))

    def find(
        self, collection: str, field: str, value: Any, limit: int | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        def get(doc: Any) -> Any:
            for key in field.split("."):
                doc = doc.get(key) if isinstance(doc, dict) else None
            return doc

        found = [(i, self.read(c, i)) for (c, i), d in list(self.docs.items()) if c == collection and get(d) == value]
        return found[:limit]  # type: ignore[return-value]

    def commit(self, writes: list[tuple[str, str, dict[str, Any], int | None]], appends: dict[str, list[dict]]) -> None:
        for coll, i, *_ in writes:
            _check(coll, i)
        for w in appends:
            _check("worlds", w)
        with self.lock:
            for coll, i, _, expect in writes:
                if not _fresh(self.docs.get((coll, i)), expect):
                    raise StaleRev
            for coll, i, data, expect in writes:
                self.docs[(coll, i)] = _plain(_stored(coll, data, expect, self.docs.get((coll, i))))
            for w, parts in appends.items():
                queued = self.queues.setdefault(w, [])
                queued += [_plain(p) for p in parts if p["id"] not in {q["id"] for q in queued}]

    def ack(self, world_id: str, part_id: str) -> None:
        _check("worlds", world_id)
        with self.lock:
            self.queues[world_id] = [p for p in self.queues.get(world_id, []) if p["id"] != part_id]


class FirestoreBackend:
    """`orgs/{org}/worlds|tasks|policies/{id}` and `worlds/{world}/_pending/queue` over one client (ADR-0026)."""

    def __init__(self, client: Any, *, org_id: str = deps.ORG_ID) -> None:
        self.client, self.org_id = client, org_id

    def _ref(self, collection: str, doc_id: str, *tail: str) -> Any:
        _check(collection, doc_id)
        return self.client.document("/".join(("orgs", self.org_id, collection, doc_id, *tail)))

    def _queue(self, world_id: str) -> Any:
        return self._ref("worlds", world_id, "_pending", "queue")

    @staticmethod
    def _enc(coll: str, doc: dict[str, Any]) -> dict[str, Any]:
        return {**doc, **{f: json.dumps(doc[f]) for f in _JSON_FIELDS.get(coll, ()) if f in doc}}

    @staticmethod
    def _dec(coll: str, doc: dict[str, Any]) -> dict[str, Any]:
        return {**doc, **{f: json.loads(doc[f]) for f in _JSON_FIELDS.get(coll, ()) if isinstance(doc.get(f), str)}}

    def read(self, collection: str, doc_id: str) -> dict[str, Any] | None:
        doc = self._ref(collection, doc_id).get().to_dict()
        return None if doc is None else self._dec(collection, doc)

    def world_ids(self) -> Iterator[str]:
        # Startup is service-owned (max one instance, ADR-0026), never selected by a request's owner/body.
        for doc in self.client.collection(f"orgs/{self.org_id}/worlds").select([]).stream():
            yield doc.id

    def queue(self, world_id: str) -> list[dict[str, Any]]:
        doc = self._queue(world_id).get().to_dict() or {}
        return [json.loads(p) for p in doc.get("parts", [])]

    def find(
        self, collection: str, field: str, value: Any, limit: int | None = None
    ) -> list[tuple[str, dict[str, Any]]]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection(f"orgs/{self.org_id}/{collection}").where(filter=FieldFilter(field, "==", value))
        if limit is not None:
            query = query.limit(limit)
        return [(d.id, self._dec(collection, d.to_dict())) for d in query.stream()]

    def commit(self, writes: list[tuple[str, str, dict[str, Any], int | None]], appends: dict[str, list[dict]]) -> None:
        from google.cloud import firestore

        @firestore.transactional  # type: ignore[misc]
        def run(tx: Any) -> None:
            held = [(self._ref(c, i), c, d, e) for c, i, d, e in writes]
            current = [ref.get(transaction=tx).to_dict() for ref, *_ in held]
            queues = {w: self._queue(w) for w in appends}
            queued = {w: (ref.get(transaction=tx).to_dict() or {}).get("parts", []) for w, ref in queues.items()}
            if not all(_fresh(cur, e) for (_, _, _, e), cur in zip(held, current, strict=True)):
                raise StaleRev
            for (ref, coll, data, expect), cur in zip(held, current, strict=True):
                tx.set(ref, self._enc(coll, _stored(coll, data, expect, cur)))
            for w, parts in appends.items():
                seen = {json.loads(p)["id"] for p in queued[w]}
                new = [json.dumps(p, sort_keys=True) for p in parts if p["id"] not in seen]
                tx.set(queues[w], {"parts": [*queued[w], *new]})

        run(self.client.transaction())

    def ack(self, world_id: str, part_id: str) -> None:
        from google.cloud import firestore

        ref = self._queue(world_id)

        @firestore.transactional  # type: ignore[misc]
        def run(tx: Any) -> None:
            parts = (ref.get(transaction=tx).to_dict() or {}).get("parts", [])
            tx.set(ref, {"parts": [p for p in parts if json.loads(p)["id"] != part_id]})

        run(self.client.transaction())


class DurableStore(deps.Store):
    def __init__(self, backend: Any, events_backend: Any, *, org_id: str = deps.ORG_ID) -> None:
        super().__init__()
        self.backend, self.events_backend, self.org_id = backend, events_backend, org_id
        self.writer: deps.EventWriter | None = None  # `settle` and the loads' drain go through it
        self.revs: dict[tuple[str, str], int] = {}
        self.unsaved: dict[str, set[str]] = {"policies": set(), "worlds": set()}  # kill-switch changes not yet stored
        self._owners: set[str] = set()
        self._settled: set[str] = set()
        self._lock = threading.RLock()
        self._marks = threading.Lock()  # for `unsaved` alone, so marking a change never waits behind a commit
        self._mark_gen: dict[tuple[str, str], int] = {}  # each mark's generation: a commit clears only what it saw
        self._gen = 0
        self._wait = threading.local()

    # -- the process-wide lock: held for dict changes and across a commit (so `rev`s stay in order), never for a load
    @contextmanager
    def _held(self) -> Iterator[None]:
        at = getattr(self._wait, "at", None)
        if not self._lock.acquire(timeout=-1 if at is None else max(0.0, at - time.monotonic())):
            raise HTTPException(status_code=503, detail="store_unavailable")
        try:
            yield
        finally:
            self._lock.release()

    @contextmanager
    def deadline(self, seconds: float) -> Iterator[None]:
        """Within this block the calling thread waits at most `seconds` in all for the lock (else 503)."""
        before = getattr(self._wait, "at", None)
        self._wait.at = time.monotonic() + seconds
        try:
            yield
        finally:
            self._wait.at = before

    # -- loads: a miss is never cached, and an id that is not its schema's never reaches the backend
    def _doc(self, coll: str, doc_id: Any) -> dict[str, Any] | None:
        if not _valid(coll, doc_id):
            return None
        with _io():
            return self.backend.read(coll, doc_id)

    def _adopt_world(self, w: str, d: Mapping[str, Any]) -> bool:
        if w == deps.SAMPLE_WORLD_ID:  # STARTER-1: a stored doc under the reserved id is never a world
            return False
        with _io():  # all the I/O and decoding first: the lock is only for the dicts
            record, rev = _world_from(d), d["rev"]
            stream, queued = self.events_backend.read_events(self.org_id, w), self.backend.queue(w)
        with self._held():
            if w in self.worlds:
                return False
            self.events[w], self.pending_events[w], self.revs[("worlds", w)], self.worlds[w] = (
                stream,
                queued,
                rev,
                record,
            )
            return True

    def _adopt_policy(self, p: str, d: Mapping[str, Any], settle: bool) -> None:
        with _io():
            rev, record, world_id = d["rev"], d["record"], d["world_id"]
        with self._held():
            if p not in self.policies:
                self.revs[("policies", p)], self.policies[p], self.policy_worlds[p] = rev, record, world_id
        if world_id:
            self.load_world(world_id, settle=settle)

    def settle(self, world_id: str, writer: deps.EventWriter | None = None, *, restart_reason: str = RESTARTED) -> None:
        """What a previous process left, once per world: its queue is sent, and a started world with no end, no run
        and no pause is closed with one `world.failed` (a stable id, so two loaders never write two). Writes: call it
        only after the route's own ownership or membership check."""
        writer = writer or self.writer
        if writer is None or world_id in self._settled or world_id not in self.worlds:
            return
        try:
            self.drain(world_id, writer)
            types = {e["type"] for e in self.events.get(world_id, [])}
            record = self.worlds[world_id]
            if (
                "world.started" in types
                and not types & {"world.completed", "world.failed"}
                and not (record.paused or world_id in self.runs)
            ):
                writer.append(world_id, events.world_failed_part(world_id, restart_reason, record.run_id))
            self._settled.add(world_id)
        except Exception as exc:  # a busy lease belongs to whoever holds it; the next look tries again
            logger.warning("settling world %s failed (%s)", world_id, type(exc).__name__)

    def recover_started_worlds(self) -> None:
        """X-ORPHAN-1: settle durable worlds before serving requests, using the existing lease and stable event id.

        An active lease is never stolen. A failed recovery stays eligible for the existing owner-load retry.
        Paused worlds and in-process runs retain settle's exclusion; no mail, model or outbox is called here.
        """
        for world_id in self.backend.world_ids():
            if not _valid("worlds", world_id):
                continue
            try:
                self.load_world(world_id)
                self.settle(world_id, restart_reason=STARTUP_RESTARTED)
            except Exception as exc:
                logger.warning("startup world recovery failed (%s)", type(exc).__name__)

    def load_world(self, world_id: str, settle: bool = False) -> deps.WorldRecord | None:
        if world_id not in self.worlds and (d := self._doc("worlds", world_id)) is not None:
            self._adopt_world(world_id, d)
        if settle:
            self.settle(world_id)
        return self.worlds.get(world_id)

    def load_task(self, task_id: str, settle: bool = False) -> deps.TaskRecord | None:
        if task_id not in self.tasks and (d := self._doc("tasks", task_id)) is not None:
            with _io():
                task, rev = _task_from(d), d["rev"]
            with self._held():
                self.revs[("tasks", task_id)], self.tasks[task_id] = rev, task
        found = self.tasks.get(task_id)
        if found is not None:
            self.load_world(found.world_id, settle=settle)
        return found

    def load_owner(self, owner: str, settle: bool = False) -> None:
        if owner not in self._owners:
            with _io():
                worlds, policies = (
                    self.backend.find("worlds", "owner", owner),
                    self.backend.find("policies", "record.owner", owner),
                )
            for w, d in worlds:
                if _valid("worlds", w):
                    self._adopt_world(w, d)
            for p, d in policies:
                if _valid("policies", p):
                    self._adopt_policy(p, d, settle=False)
            self._owners.add(owner)
        if settle:
            for w in [w for w, r in list(self.worlds.items()) if r.owner == owner]:
                self.settle(w)

    def load_world_task(self, world_id: str) -> deps.TaskRecord | None:
        """Read-only (PEOPLE-SEAMS-1): the task stored for this world, cached or read by `world_id` (one document at
        most); None for none, and for an id that is not a world's."""
        cached = super().load_world_task(world_id)
        if cached is not None or not _valid("worlds", world_id):
            return cached
        with _io():
            found = self.backend.find("tasks", "world_id", world_id, limit=1)
        for task_id, d in found:
            if not _valid("tasks", task_id) or d.get("world_id") != world_id:
                continue
            with _io():
                task, rev = _task_from(d), d["rev"]
            with self._held():
                if task_id not in self.tasks:
                    self.revs[("tasks", task_id)], self.tasks[task_id] = rev, task
            return self.tasks[task_id]
        return None

    def load_path(self, params: Mapping[str, Any]) -> DurableStore:
        """The ids of a request's path, read-only: this runs before the route has checked who is asking."""
        self.load_world(params.get("world_id"), settle=False)  # type: ignore[arg-type]
        self.load_task(params.get("task_id"), settle=False)  # type: ignore[arg-type]
        p = params.get("policy_id")
        if (
            isinstance(p, str)
            and _valid("policies", p)
            and p not in self.policies
            and (d := self._doc("policies", p)) is not None
        ):
            self._adopt_policy(p, d, settle=False)
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
        deps.refuse_reserved(
            worlds, parts=parts, policy_worlds=policy_worlds, tasks=tasks
        )  # STARTER-1: no real world takes the sample project's id
        made, parts = set(create), {w: list(p) for w, p in (parts or {}).items() if p}
        with self._held():
            with self._marks:  # the marks before these records are read: a later mark is a change they may not hold
                marked = {c: set(ids) for c, ids in self.unsaved.items()}
            # Every commit also writes the kill switches' unsaved changes, always from the cached record (never a
            # caller's copy), so a pause is stored by the next commit that lands, whichever request it is.
            worlds = {**(worlds or {}), **{i: self.worlds[i] for i in marked["worlds"] if i in self.worlds}}
            policies = {**(policies or {}), **{i: self.policies[i] for i in marked["policies"] if i in self.policies}}
            carried = {("worlds", i) for i in marked["worlds"]} | {("policies", i) for i in marked["policies"]}
            mapped = {p: (policy_worlds or {}).get(p, self.policy_worlds.get(p)) for p in policies}
            with self._marks:
                seen = {("worlds", i): self._mark_gen.get(("worlds", i)) for i in worlds}
                seen |= {("policies", i): self._mark_gen.get(("policies", i)) for i in policies}
            records = [("worlds", i, _plain(r)) for i, r in (worlds or {}).items()]
            records += [("tasks", i, _task_doc(r)) for i, r in (tasks or {}).items()]
            records += [
                ("policies", i, {"record": _plain(r), "world_id": mapped[i]}) for i, r in (policies or {}).items()
            ]
            touched = [(c, i) for c, i, _ in records]
            try:
                # a carried change is authoritative here: its `rev`, unknown after its own failed commit, is re-read
                writes = [
                    (c, i, d, self._expect(c, i, (c, i) in made, not evict or (c, i) in carried)) for c, i, d in records
                ]
                self.backend.commit(writes, parts)
            except Exception as exc:
                self._evict(touched, parts, forget=evict)
                if isinstance(exc, StaleRev):
                    raise HTTPException(status_code=409, detail="stale") from None
                logger.warning("api store commit failed (%s)", type(exc).__name__)
                raise HTTPException(status_code=503, detail="store_unavailable") from exc
            for c, i, _, expect in writes:
                self.revs[(c, i)] = (expect or 0) + 1
            with self._marks:  # a mark set after `seen` is a change this commit did not write: it stays
                for (c, i), gen in seen.items():
                    if gen is not None and self._mark_gen.get((c, i)) == gen:
                        self.unsaved[c].discard(i)
                        del self._mark_gen[(c, i)]
                held = {c: set(ids) for c, ids in self.unsaved.items()}
            # a cached record a kill switch changed in place and has not saved is never replaced by a caller's copy
            self.worlds.update(
                {i: r for i, r in (worlds or {}).items() if i not in held["worlds"] or i not in self.worlds}
            )
            self.tasks.update(tasks or {})
            self.policies.update(
                {i: r for i, r in (policies or {}).items() if i not in held["policies"] or i not in self.policies}
            )
            self.policy_worlds.update({p: w for p, w in mapped.items() if w})
            for w, new in parts.items():
                queued = self.pending_events.get(w, [])
                self.pending_events[w] = [*queued, *(p for p in new if p["id"] not in {q["id"] for q in queued})]

    def commit_unsaved(
        self, touched: Iterable[str] = (), *, policies: Iterable[str] = (), worlds: Iterable[str] = ()
    ) -> None:
        """A kill switch's commit (FR-HIL-07): marks what it changed in place, then writes every change still unsaved
        (this call's and any earlier failed one's) with the queued parts of every world they belong to. Raises 503 or
        409 if that does not land; the changes stay applied here and marked."""
        with self._marks:  # marked first, outside the big lock: a commit that cannot start still leaves them marked
            for coll, ids in (("policies", policies), ("worlds", worlds)):
                for i in ids:
                    self._gen += 1
                    self.unsaved[coll].add(i)
                    self._mark_gen[(coll, i)] = self._gen
            marked_policies, marked_worlds = set(self.unsaved["policies"]), set(self.unsaved["worlds"])
        with self._held():
            ps = {p: self.policies[p] for p in marked_policies if p in self.policies}
            ws = {w: self.worlds[w] for w in marked_worlds if w in self.worlds}
            wanted = {*touched, *ws, *(self.policy_worlds[p] for p in ps if p in self.policy_worlds)}
            parts = {w: list(q) for w in wanted if isinstance(q := self.pending_events.get(w), list) and q}
            if ps or ws or parts:
                self.commit(policies=ps, worlds=ws, parts=parts, evict=False)

    def _expect(self, coll: str, doc_id: str, creating: bool, authoritative: bool) -> int | None:
        """The `rev` a write must find: none for a create. An in-place change (a kill switch, the layout) is
        authoritative here, so a `rev` that a failed commit made unknown is read again rather than refused. Any other
        write whose `rev` is unknown expects none, which `_fresh` reads as a create: on an existing document that is a
        409 `stale` (safe, if confusing after a failed kill switch; the entry was evicted and reloads)."""
        if creating:
            return None
        if (coll, doc_id) in self.revs or not authoritative:
            return self.revs.get((coll, doc_id))
        doc = self.backend.read(coll, doc_id)
        return None if doc is None else doc["rev"]

    def _evict(self, touched: list[tuple[str, str]], parts: Mapping[str, Any], *, forget: bool) -> None:
        """After a failed commit the `rev` of what it touched is unknown. `forget` also drops the cached entries (but
        never a kill switch's unsaved change), so the next access reloads what is really stored; a world that stays
        cached gets its durable queue read again, never dropped."""
        cached: dict[str, dict[str, Any]] = {"worlds": self.worlds, "tasks": self.tasks, "policies": self.policies}
        for coll, i in touched:
            self.revs.pop((coll, i), None)
            if forget and i not in self.unsaved.get(coll, ()):
                cached[coll].pop(i, None)
                if coll == "worlds":
                    self.events.pop(i, None)
                    self.pending_events.pop(i, None)
                    self._settled.discard(i)
        if not forget:
            return
        self._owners.clear()  # an evicted world is found again by the next `load_owner`
        for w in parts:
            if w not in self.worlds or w in self.unsaved["worlds"]:  # a kill switch's unsaved world keeps its cache
                continue
            try:
                self.pending_events[w] = self.backend.queue(w)
            except Exception as caught_error:
                log_caught(caught_error, __name__, locals())
                self.worlds.pop(w, None)
                self.events.pop(w, None)
                self.pending_events.pop(w, None)
                self.revs.pop(("worlds", w), None)

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
                log_caught(exc, __name__, locals())
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


def recover_deployed() -> None:
    """Only a configured durable API opens a store at startup. An outage keeps the normal route-level 503s."""
    if os.environ.get(store_door.ENV_STORE) != "firestore":
        return
    try:
        deployed()[0].recover_started_worlds()
    except Exception as exc:
        logger.warning("startup recovery unavailable (%s)", type(exc).__name__)


def close_deployed() -> None:
    """On shutdown (SIGTERM): every writer closes and releases its lease, so a new revision does not wait it out. The
    whole call is bounded (`_CLOSE_BUDGET_S`): a busy world is skipped, and its lease lapses by itself."""
    end = time.monotonic() + _CLOSE_BUDGET_S
    got = _opening.acquire(timeout=1.0)  # a client being built does not hold the shutdown up
    try:
        writers = [writer for _, writer in _opened.values()]
    finally:
        if got:
            _opening.release()
    for writer in writers:
        reopen = getattr(writer, "reopen", None)
        if callable(reopen) and (left := end - time.monotonic()) > 0:
            reopen(left)
