"""PROD-WIRE slice 1b helpers (ADR-0026 decisions 2, 3, 5, 8). Kept out of conftest.py under a package-unique name.

Pinned interface, the same for every test of slice 1b (`tilo_api.durable_store`):

- `DurableStore(backend, events_backend, *, org_id=deps.ORG_ID)` is a `deps.Store` (plain dicts `worlds`, `tasks`,
  `policies`, `policy_worlds`, `events`, `pending_events`) plus `.backend`, `.events_backend` and `.writer` (an
  `EventWriter` or None; the loads drain and fail through it). The store calls `backend.commit(...)` at call time,
  exactly once per `store.commit(...)`. A `rev` starts at 1 and grows by 1 per commit that writes the record.
  - `load_world(w)`, `load_task(t)`: the record from the backend or None; a miss is never cached; an id that does
    not match its common.schema.json pattern is None with no backend read. Loading a world reads its events by
    `seq` from `events_backend`, reads its queue, drains it through `writer`, then applies decision 5's restart rule.
  - `load_owner(owner)` loads that owner's worlds (events included) and policies; `load_path(path_params)` loads
    the `world_id`, `task_id` and `policy_id` of a request and returns the store (`deps.get_store(request)` does it).
  - `commit(*, worlds=None, tasks=None, policies=None, policy_worlds=None, parts=None, create=())`: `worlds`, `tasks`
    are `{id: record}`, `policies` is `{policy_id: policy record}` with `policy_worlds` `{policy_id: world_id}`,
    `parts` is `{world_id: [event part, ...]}` and `create` is `[("worlds"|"tasks"|"policies", id), ...]`. One
    rev-checked backend transaction writes the records and appends the parts to the queue; only then does the cache
    change. A failed or ambiguous commit raises HTTPException 503 `store_unavailable` and evicts the touched
    entries; a rev mismatch, or creating what exists, raises 409 `stale` (the entries are evicted too).
  - `drain(world_id, writer=None)`: appends the queued parts oldest first through `writer` (default `self.writer`),
    removing each from the queue and the cache once committed; the first failure stops it (503 `store_unavailable`)
    and the rest stay queued.
- A backend (`MemoryBackend()`, `FirestoreBackend(client, *, org_id)`): `read(collection, doc_id)` is the stored
  document (`worlds`, `tasks`: the record's fields plus `rev`; `policies`: `{record, world_id, rev}`) or None;
  `queue(world_id)` is `worlds/{w}/_pending/queue`'s parts; `commit(...)` is its one write.
- `store_door.FirestoreApiStore(project, client)` has `.records` (a `FirestoreBackend`) and `.events` (the harness
  store protocol over the same client); `store_door.client_factory` is the injection point `deps.get_store` and
  `deps.get_event_writer` hand to `open_api_store`.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from _api_lib import base_policy, ulid
from fastapi import Request
from tilo_api import deps
from tilo_api.durable_store import DurableStore, FirestoreBackend, MemoryBackend
from tilo_api.world_writer import WorldWriterAdapter
from tilo_harness.store import FirestoreStore, MemoryStore
from tilo_planning.gaps import Gap
from tilo_planning.questions import Question

OWNER, OTHER = "u_pw1b_owner", "u_pw1b_other"
W1, W2, W3 = "w_pw1b_one", "w_pw1b_two", "w_pw1b_three"
T1, RUN, P1, P2, P3 = "t_" + ulid(1), "r_pw1b_1", "pol_pw1b_a", "pol_pw1b_b", "pol_pw1b_c"
AT = "2026-10-07T01:00:00.000Z"
RESTARTED = "the service restarted, so the work stopped"


@dataclass
class PwRig:
    """One backend and one events store, shared by every `process()`: a process is a store and its writer."""

    org: str
    backend: Any
    events: Any

    def process(self, clock: Any = None) -> tuple[DurableStore, WorldWriterAdapter]:
        store = DurableStore(self.backend, self.events, org_id=self.org)
        store.writer = WorldWriterAdapter(store, self.events, org_id=self.org, clock=clock)
        return store, store.writer

    def stream(self, world: str) -> list[dict]:
        return self.events.read_events(self.org, world)


def make_rig(kind: str) -> PwRig:
    if kind == "memory":
        return PwRig(deps.ORG_ID, MemoryBackend(), MemoryStore())
    from google.cloud import firestore

    org = f"org_pw1b_{uuid.uuid4().hex[:12]}"  # a fresh org per test: the emulator keeps what earlier tests wrote
    return PwRig(org, FirestoreBackend(firestore.Client(project="demo-pw1b"), org_id=org), FirestoreStore("demo-pw1b"))


def world(**over: Any) -> deps.WorldRecord:
    fields = {
        "owner": OWNER, "districts": {"D1": deps.DistrictRecord("Sales", "Sells things")},
        "owner_channels": ("web", "email"), "run_id": RUN,
    }  # fmt: skip
    return deps.WorldRecord(**(fields | over))


def task(world_id: str = W1, **over: Any) -> deps.TaskRecord:
    brief = {"title": "Compare prices", "sources": [], "audience": None}
    record = deps.TaskRecord(
        OWNER, world_id, RUN, brief, brief, [Question("audience", "Who is it for?", ("team",), 0.4)], 3
    )
    record.answers, record.edits, record.granted = {"audience": None}, {"title": "Compare"}, False
    record.approaches = [{"id": "quick", "credits": {"min": 1, "max": 2}}]
    record.gaps = (Gap("travel", "book flights", "Tilo cannot book travel.", "Use a travel site."),)
    for name, value in over.items():
        setattr(record, name, value)
    return record


def policy(pid: str, *, owner: str = OWNER, level: str = "L2") -> dict:
    return base_policy(id_=pid, owner=owner, level=level)


def part(n: int, **over: Any) -> dict:
    """An event part as tilo-api builds one: its own id and `vis`, no `seq`, `ts` or `run_id`."""
    base = {
        "id": ulid(n), "type": "agent.idle", "actor": "A_director", "target": "A_director", "level": None,
        "district": None, "item": None, "severity": "info", "credits": 0, "cause": None, "vis": "all", "authz": None,
        "summary": "The Director is waiting.", "data": {},
    }  # fmt: skip
    return base | over


def requested(n: int, w: str = W1) -> dict:
    data = {"title": "Do some work", "channel": "web", "destination": None}
    return part(n, type="world.requested", actor=OWNER, target=w, summary="You asked Tilo.", data=data)


def started(n: int, w: str = W1) -> dict:
    return part(n, type="world.started", target=w, summary="Work started.", data={"budget_cap": 40})


def granted(n: int, w: str, cap: int) -> dict:
    authz = {"by": "person", "ref": OWNER, "at": AT}
    return part(n, type="budget.granted", actor=OWNER, target=w, authz=authz, data={"granted": cap, "cap": cap})


def ended(n: int, w: str = W1) -> dict:
    return part(n, type="world.completed", target=w, summary="Done.", data={"deliverable_count": 0, "credits_used": 0})


def ids(parts: list[dict]) -> list[str]:
    return [p["id"] for p in parts]


def seed(store: DurableStore, *, worlds=None, tasks=None, policies=None, policy_worlds=None, parts=None) -> None:
    made = [("worlds", w) for w in worlds or {}] + [("tasks", t) for t in tasks or {}]
    store.commit(
        worlds=worlds, tasks=tasks, policies=policies, policy_worlds=policy_worlds, parts=parts,
        create=made + [("policies", p) for p in policies or {}],
    )  # fmt: skip


@contextmanager
def commits_fail(backend: Any, *, applied: bool = False):
    """The backend's commit raises; with `applied` it lands first (an ambiguous answer: the deadline passed)."""
    real = backend.commit

    def run(*args: Any, **kwargs: Any) -> None:
        if applied:
            real(*args, **kwargs)
        raise TimeoutError("the commit did not answer")

    backend.commit = run
    try:
        yield
    finally:
        del backend.commit


class FlakyWriter:
    """Fails its `fail_on`th append (before the commit, or after it: an ambiguous answer); `fail_on=0` fails all."""

    def __init__(self, inner: Any, fail_on: int = 0, *, after_commit: bool = False) -> None:
        self.inner, self.fail_on, self.after_commit, self.calls = inner, fail_on, after_commit, 0

    def append(self, world_id: str, event: dict) -> dict:
        self.calls += 1
        if self.fail_on in (0, self.calls):
            if self.after_commit:
                self.inner.append(world_id, event)
            raise ConnectionError("the event store is down")
        return self.inner.append(world_id, event)

    def reopen(self) -> None:
        self.inner.reopen()


def wire(app: Any, store: DurableStore, writer: Any = None) -> None:
    """The deployed seams over `store`: the request's path ids are loaded first, as `deps.get_store` does."""

    def get_store(request: Request) -> DurableStore:
        return store.load_path(request.path_params)

    app.dependency_overrides[deps.get_store] = get_store
    app.dependency_overrides[deps.get_event_writer] = lambda: writer or store.writer
