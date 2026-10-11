"""Ephemeral demo sessions (DEMO-EPHEMERAL-1, BQ-DEMO-EPH-1): an anonymous demo session stores nothing durable.

Every write a demo makes (tasks, worlds, events, cards, policies and grants, memory, the run's outputs and raw archive,
the outbox, uploads, people records) lands in a per-session in-memory bundle (`DemoSession`) held by a process-wide
`Registry`, keyed by the uid of the VERIFIED token (`Principal.user_id`, never a header or a body). A bundle is dropped
when its session has been idle for `TTL_S`, or by `Registry.drop`; every access sweeps the expired ones, so no thread
is needed. Nothing here opens Firestore, writes a file or calls a connector: the `deps` seams give a demo request its
bundle in place of the durable ones, and a full (Google) session never reaches this module's bundles.

Caps fail closed and never evict: no new session at `MAX_SESSIONS` (503 `demo_capacity`), no write past a session's
`MAX_ITEMS`/`MAX_BYTES` (429 `demo_capacity`), none past the process-wide totals (503 `demo_capacity`). Where a request
cannot be shown to be a full session (no principal that resolves), `for_request` refuses with the fixed sign-in 401:
never "persist".
"""

from __future__ import annotations

import logging
import threading
import time
import weakref
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from starlette.requests import HTTPConnection
from tilo_archive import RunArchive
from tilo_connectors import InMemoryOutboxStore
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend
from tilo_people.stores import PeopleStores
from tilo_planning.artifacts import InMemoryArtifactStore
from tilo_redact import redact as _redact
from tilo_redact import redact_value as _redact_payload

from tilo_api import deps

logger = logging.getLogger("tilo_api.ephemeral")

TTL_S = 1800.0  # idle time after which a session's data is gone
MAX_SESSIONS = 100
MAX_ITEMS = 1000  # per session: records, events, artifact documents and blobs, archive lines, uploads, people records
MAX_BYTES = 8_000_000  # per session: artifact blobs, archive lines, uploads
MAX_TOTAL_ITEMS = 20_000
MAX_TOTAL_BYTES = 100_000_000
MAX_RUNS = 2  # a demo's runs at once
IDLE_EMPTY_S = 60.0  # an empty session older than this may be evicted for a new one
CAPACITY = "demo_capacity"


def _capacity(status: int) -> HTTPException:
    return HTTPException(status_code=status, detail=CAPACITY)


class _Counted:
    """Mixin for the in-memory backends: each new item is charged to the session first, so a full session refuses."""

    session: DemoSession

    def charge(self, items: int = 1, nbytes: int = 0) -> None:
        self.session.charge(items, nbytes)

    def charged(self, call: Callable[[], Any], items: int = 1, nbytes: int = 0) -> Any:
        """`call` after charging; a refused or failed write gives the charge back."""
        self.charge(items, nbytes)
        try:
            return call()
        except BaseException:
            self.session.refund(items, nbytes)
            raise


class _Meta(_Counted, MemoryMetaBackend):
    def __init__(self, session: DemoSession) -> None:
        super().__init__()
        self.session = session

    def create(self, path: str, doc: dict[str, Any]) -> None:
        self.charged(lambda: super(_Meta, self).create(path, doc))


class _Blobs(_Counted, MemoryBlobBackend):
    def __init__(self, session: DemoSession) -> None:
        super().__init__()
        self.session = session

    def create(self, key: str, data: bytes) -> None:
        self.charged(lambda: super(_Blobs, self).create(key, data), 1, len(data))


class _Uploads(_Counted, InMemoryArtifactStore):
    def __init__(self, session: DemoSession) -> None:
        super().__init__()
        self.session = session

    def put(self, **kwargs: Any) -> Any:
        return self.charged(lambda: super(_Uploads, self).put(**kwargs), 1, len(kwargs.get("content", b"")))


class _Outbox(_Counted, InMemoryOutboxStore):
    def __init__(self, session: DemoSession) -> None:
        super().__init__()
        self.session = session

    def _insert_if_absent(self, entry: dict) -> bool:
        self.charge()
        added = False
        try:
            added = super()._insert_if_absent(entry)
            return added
        finally:
            if not added:
                self.session.refund(1, 0)


class _ArchiveLines:
    """The raw archive's line store (`tilo_archive.Store`): in memory, charged, gone with the session."""

    def __init__(self, session: DemoSession) -> None:
        self._session, self._lines, self._lock = session, {}, threading.Lock()

    def append_line(self, org_id: str, run_id: str, line: str) -> None:
        self._session.charge(1, len(line.encode()))
        with self._lock:
            self._lines.setdefault((org_id, run_id), []).append(line)

    def read_lines(self, org_id: str, run_id: str) -> list[str]:
        with self._lock:
            return list(self._lines.get((org_id, run_id), []))


class EphemeralStore(deps.Store):
    """The plain in-memory `deps.Store`, charging every new world, task and policy to its session."""

    session: DemoSession
    _busy = threading.local()

    def admit_run(self) -> None:
        """At most `MAX_RUNS` runs at once: each parked run keeps a polling thread (429 `demo_runs_busy`)."""
        if sum(not r._ended.is_set() for r in list(self.runs.values())) >= MAX_RUNS:
            raise HTTPException(status_code=429, detail="demo_runs_busy")

    def _new(self, worlds: Any, tasks: Any, policies: Any) -> int:
        return sum(
            k not in d
            for given, d in ((worlds, self.worlds), (tasks, self.tasks), (policies, self.policies))
            for k in given or ()
        )

    def _charged(self, call: Callable[..., Any], new: int, *args: Any, **kwargs: Any) -> Any:
        if getattr(self._busy, "on", False):  # `save` calls `commit`: charged once, by the outer call
            return call(*args, **kwargs)
        self.session.charge(new)
        self._busy.on = True
        try:
            return call(*args, **kwargs)
        except BaseException:
            self.session.charge(-new)
            raise
        finally:
            self._busy.on = False

    def commit(self, *, worlds=None, tasks=None, policies=None, **rest: Any) -> None:  # type: ignore[no-untyped-def]
        new = self._new(worlds, tasks, policies)
        self._charged(super().commit, new, worlds=worlds, tasks=tasks, policies=policies, **rest)

    def save(self, writer: Any, *, parts: Any = None, **records: Any) -> None:
        new = self._new(records.get("worlds"), records.get("tasks"), records.get("policies"))
        self._charged(super().save, new, writer, parts=parts, **records)


def _writer(store: EphemeralStore, session: DemoSession) -> Any:
    from tilo_api.dev import DevEventWriter  # noqa: PLC0415 (dev imports deps; the validator and stamping are shared)

    class Writer(DevEventWriter):
        def _guard(self) -> None:  # dev mode's "never deployed" check does not apply: this writer only holds memory
            return None

        def append(self, world_id: str, event: dict) -> dict:
            if not any(e.get("id") == event.get("id") for e in store.events.get(world_id, [])):
                session.charge()
            return super().append(world_id, event)

    return Writer(store)


class DemoSession:
    """One demo's data: all of it in this object, nothing anywhere else."""

    def __init__(self, registry: Registry, uid: str) -> None:
        self.registry, self.uid, self.items, self.nbytes, self.dead = registry, uid, 0, 0, False
        self.last_seen = registry.clock()
        self.registered = False  # a session holds a registry slot only once it has stored something
        self._lock = threading.Lock()
        self._made: dict[str, Any] = {}
        self.store = EphemeralStore()
        self.store.session = self
        self.writer = _writer(self.store, self)

    def charge(self, items: int = 1, nbytes: int = 0) -> None:
        self.registry.charge(self, items, nbytes)

    def _once(self, name: str, make: Callable[[], Any]) -> Any:
        with self._lock:
            if name not in self._made:
                self._made[name] = make()
            return self._made[name]

    @property
    def outbox(self) -> InMemoryOutboxStore:
        return self._once("outbox", lambda: _Outbox(self))

    @property
    def uploads(self) -> InMemoryArtifactStore:
        return self._once("uploads", lambda: _Uploads(self))

    @property
    def artifacts(self) -> ArtifactStore:
        return self._once("artifacts", lambda: ArtifactStore(
            _Meta(self), _Blobs(self), clock=lambda: datetime.now(UTC), redactor=_redact,
            archive_lookup=lambda scope, archive_ref: None, alert_sink=lambda alert: logger.info("demo artifact alert"),
        ))  # fmt: skip

    @property
    def redactor(self) -> Callable[[str], str]:
        return _redact

    @property
    def open_archive(self) -> Callable[..., RunArchive]:
        lines = self._once("archive", lambda: _ArchiveLines(self))

        def open_archive(*, org_id: str, run_id: str) -> RunArchive:
            return RunArchive(lines, org_id=org_id, run_id=run_id, redactor=_redact_payload)

        return open_archive

    @property
    def people(self) -> PeopleStores:
        def make() -> PeopleStores:
            stores = PeopleStores.in_memory()  # the real person store: address reservation, founder marker, last person
            for store in (
                stores.persons,
                stores.meetings,
                stores.work_items,
                stores.pins,
                stores.mentions,
                stores.calendar,
            ):
                for name in ("create", "create_founder"):
                    if hasattr(store, name):
                        setattr(store, name, self._charging(getattr(store, name)))
            stamp = {"by": self.uid, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
            stores.persons.create(
                {"id": self.uid, "org_id": deps.ORG_ID, "display_name": "Demo", "aliases": [],
                 "email": "demo@example.com", "time_zone": "Asia/Kolkata", "preferred_channel": "web",
                 "org_role": "owner", "memberships": [], "created_by": stamp}
            )  # fmt: skip
            return stores

        return self._once("people", make)

    def _charging(self, create: Callable[[Any], Any]) -> Callable[[Any], Any]:
        def charged(record: Any) -> Any:
            self.charge()
            try:
                return create(record)
            except BaseException:
                self.refund(1, 0)
                raise

        return charged

    def refund(self, items: int, nbytes: int) -> None:
        self.registry.refund(self, items, nbytes)

    def clear(self) -> None:
        self.dead = True
        for held in (self.store.worlds, self.store.tasks, self.store.policies, self.store.events, self.store.runs):
            held.clear()
        if self._lock.acquire(timeout=1.0):  # never wait on a builder that holds it while it charges (lock order)
            try:
                self._made.clear()
            finally:
                self._lock.release()


class Registry:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = TTL_S,
        max_sessions: int = MAX_SESSIONS,
        max_items: int = MAX_ITEMS,
        max_bytes: int = MAX_BYTES,
        max_total_items: int = MAX_TOTAL_ITEMS,
        max_total_bytes: int = MAX_TOTAL_BYTES,
    ) -> None:
        self.clock, self.ttl_s, self.max_sessions = clock, ttl_s, max_sessions
        self.max_items, self.max_bytes = max_items, max_bytes
        self.max_total_items, self.max_total_bytes = max_total_items, max_total_bytes
        self.sessions: dict[str, DemoSession] = {}
        self._pending: weakref.WeakValueDictionary[str, DemoSession] = weakref.WeakValueDictionary()
        self.total_items = self.total_bytes = 0
        self._lock = threading.RLock()

    def session(self, uid: str) -> DemoSession:
        """The uid's live session (its idle clock restarts), or an empty one that holds no slot until it first stores
        something: a read creates nothing here."""
        with self._lock:
            self.sweep()
            held = self.sessions.get(uid) or self._pending.get(uid)
            if held is None:
                held = self._pending[uid] = DemoSession(self, uid)
            held.last_seen = self.clock()
            return held

    def _register(self, session: DemoSession) -> None:
        if len(self.sessions) >= self.max_sessions:
            now = self.clock()
            idle = [s for s in self.sessions.values() if s.items == 0 and now - s.last_seen > IDLE_EMPTY_S]
            if not idle:
                raise _capacity(503)  # never one that holds data
            self.drop(min(idle, key=lambda s: s.last_seen).uid)
        self.sessions[session.uid] = session
        self._pending.pop(session.uid, None)
        session.registered = True

    def sweep(self) -> None:
        with self._lock:
            now = self.clock()
            for uid in [u for u, s in self.sessions.items() if now - s.last_seen >= self.ttl_s]:
                self.drop(uid)

    def drop(self, uid: str) -> None:
        with self._lock:
            gone = self.sessions.pop(uid, None) or self._pending.pop(uid, None)
            if gone is not None:
                self.total_items -= gone.items
                self.total_bytes -= gone.nbytes
                gone.clear()

    def refund(self, session: DemoSession, items: int, nbytes: int) -> None:
        with self._lock:
            if not session.dead:
                session.items -= items
                session.nbytes -= nbytes
                self.total_items -= items
                self.total_bytes -= nbytes

    def charge(self, session: DemoSession, items: int, nbytes: int) -> None:
        with self._lock:
            if session.dead:
                raise _capacity(503)  # the session ended while its run was still writing
            if (items > 0 or nbytes > 0) and not session.registered:
                self._register(session)
            if items > 0 or nbytes > 0:
                if session.items + items > self.max_items or session.nbytes + nbytes > self.max_bytes:
                    raise _capacity(429)
                if self.total_items + items > self.max_total_items or self.total_bytes + nbytes > self.max_total_bytes:
                    raise _capacity(503)
            session.items += items
            session.nbytes += nbytes
            self.total_items += items
            self.total_bytes += nbytes


_registry = Registry()


def registry() -> Registry:
    return _registry


def configure(**limits: Any) -> Registry:
    """A fresh registry with these limits (tests, and nothing else: no request reaches it)."""
    global _registry
    _registry = Registry(**limits)
    return _registry


def mark_no_person(request: Any) -> None:
    """Said by the scheduler routes alone, after their OIDC check: this request has no person (no Firebase token to
    verify), so it gets the durable store and the durable run seams. Nothing a client sends sets it."""
    if (state := getattr(request, "state", None)) is not None:
        state.no_person = True


def has_no_person(request: Any) -> bool:
    state = getattr(request, "state", None)
    return state is None or getattr(state, "no_person", False) is True  # not a real request: nobody to resolve


def for_request(request: HTTPConnection) -> DemoSession | None:
    """This request's ephemeral session when it is an anonymous demo session; None for a full session. The demo flag is
    the access gate's or the verified principal's, the bucket the principal's uid: nothing a client sends picks either.
    A request whose principal cannot be resolved is refused with the sign-in 401, never given a durable store."""
    state = getattr(request, "state", None)
    if state is not None and getattr(state, "no_person", False) is True:
        return None  # the scheduler's own request (see `mark_no_person`): the durable store, as before
    if state is None:  # not a real request (no person to resolve): refused like any unresolvable principal
        raise HTTPException(status_code=401, detail=deps.SIGN_IN_REQUIRED, headers={"WWW-Authenticate": "Bearer"})
    if (held := getattr(state, "ephemeral_session", None)) is not None:
        return held or None
    principal = getattr(state, "principal", None)
    if not isinstance(principal, deps.Principal):
        try:
            principal = deps.resolve_principal(request.app, request)
        except Exception:
            raise HTTPException(
                status_code=401, detail=deps.SIGN_IN_REQUIRED, headers={"WWW-Authenticate": "Bearer"}
            ) from None
        if not isinstance(principal, deps.Principal):
            raise HTTPException(status_code=401, detail=deps.SIGN_IN_REQUIRED, headers={"WWW-Authenticate": "Bearer"})
    demo = getattr(state, "demo_session", False) is True or principal.demo_session is True
    found = _registry.session(principal.user_id) if demo else None
    state.ephemeral_session = found or False
    return found
