"""Where the world's events, views and head (lease + counters) live (PRD 15.3). `MemoryStore`
and `FirestoreStore` share the same read semantics; `WorldWriter` is the only code that calls
`transact`, which applies one head-update, at most one full-stream event and any number of view
copies atomically -- a single Python call for `MemoryStore` (nothing else can interleave inside
it), a single Firestore transaction for `FirestoreStore`, so a kill never leaves a partial
write and a superseded writer's write never lands (ticket brief items 6-8).

`FirestoreStore.transact` writes event and view documents with `transaction.create`, never
`transaction.set`: an existing `events/{seq:08d}` or `views/{scope}/events/{vseq:08d}` document
can therefore never be silently overwritten by a second writer, even one that (wrongly) still
believes it holds the world's lease -- `create` raises instead. `MemoryStore.transact` only ever
appends, for the same reason. Only the head document (lease + counters) uses `set`, since it is
the one document every writer legitimately updates in place.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tilo_harness.ids import ORG_ID, WORLD_ID, check_id, is_scope

# transact()'s callback: head -> (new_head, event_to_append_or_None, [(scope, view_doc), ...]).
# Raising (WriterBusy, EventRejected, ...) leaves the store untouched.
TransactFn = Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any] | None, list[tuple[str, dict[str, Any]]]]]

_DEMO_PROJECT = re.compile(r"^demo-[0-9a-z-]+$")


@dataclass
class _World:
    events: list[dict[str, Any]] = field(default_factory=list)
    views: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    last_seq: int = 0
    view_seq: dict[str, int] = field(default_factory=dict)
    lease: dict[str, Any] | None = None


class MemoryStore:
    """In-memory Store: same read/write semantics as FirestoreStore, for fast tests."""

    def __init__(self) -> None:
        self._worlds: dict[tuple[str, str], _World] = {}

    def _world(self, org_id: str, world_id: str) -> _World:
        return self._worlds.setdefault((org_id, world_id), _World())

    def read_events(self, org_id: str, world_id: str) -> list[dict[str, Any]]:
        return list(self._world(org_id, world_id).events)

    def read_view(self, org_id: str, world_id: str, scope: str) -> list[dict[str, Any]]:
        return list(self._world(org_id, world_id).views.get(scope, []))

    def read_head(self, org_id: str, world_id: str) -> dict[str, Any]:
        w = self._world(org_id, world_id)
        return {"last_seq": w.last_seq, "lease": dict(w.lease) if w.lease else None, "view_seq": dict(w.view_seq)}

    def transact(self, org_id: str, world_id: str, fn: TransactFn) -> dict[str, Any]:
        w = self._world(org_id, world_id)
        new_head, event, views = fn(self.read_head(org_id, world_id))
        w.last_seq = new_head["last_seq"]
        w.lease = new_head["lease"]
        w.view_seq = dict(new_head["view_seq"])
        if event is not None:
            w.events.append(event)
        for scope, doc in views:
            w.views.setdefault(scope, []).append(doc)
        return new_head


class FirestoreStore:
    """Firestore Store against the Firestore emulator only (ADR-0003: local-first, no cloud
    credentials, never a real project). Full stream: orgs/{org}/worlds/{world}/events/{seq:08d}.
    Views: orgs/{org}/worlds/{world}/views/{scope}/events/{vseq:08d}. The world head (lease,
    last_seq, each view's vseq) is orgs/{org}/worlds/{world} itself (PRD 15.3)."""

    def __init__(self, project_id: str = "demo-tilo") -> None:
        host = os.environ.get("FIRESTORE_EMULATOR_HOST")
        if not host:
            raise RuntimeError(
                "FirestoreStore refuses to start without FIRESTORE_EMULATOR_HOST (ADR-0003: "
                "emulator only, no cloud credentials); use tilo_harness.emulator.running_emulator()."
            )
        if not _DEMO_PROJECT.match(project_id):
            raise RuntimeError(f"FirestoreStore refuses a non-demo project id, got {project_id!r}")

        from google.cloud import firestore

        self.project_id = project_id
        self._client = firestore.Client(project=project_id)

    def _check_org_world(self, org_id: str, world_id: str) -> None:
        # Security-reviewer, P0-09 round 2: every path built from org_id/world_id is guarded
        # here too, independent of WorldWriter's constructor check, since this is the code that
        # actually turns these ids into a Firestore path -- see ids.py.
        check_id(org_id, ORG_ID, label="org_id")
        check_id(world_id, WORLD_ID, label="world_id")

    def _events(self, org_id: str, world_id: str):
        self._check_org_world(org_id, world_id)
        return self._client.collection(f"orgs/{org_id}/worlds/{world_id}/events")

    def _views(self, org_id: str, world_id: str, scope: str):
        self._check_org_world(org_id, world_id)
        if not is_scope(scope):
            raise ValueError(f'scope {scope!r} is not "shared" or a district id')
        return self._client.collection(f"orgs/{org_id}/worlds/{world_id}/views/{scope}/events")

    def _head(self, org_id: str, world_id: str):
        self._check_org_world(org_id, world_id)
        return self._client.document(f"orgs/{org_id}/worlds/{world_id}")

    def read_events(self, org_id: str, world_id: str) -> list[dict[str, Any]]:
        return [doc.to_dict() for doc in self._events(org_id, world_id).order_by("seq").stream()]

    def read_view(self, org_id: str, world_id: str, scope: str) -> list[dict[str, Any]]:
        return [doc.to_dict() for doc in self._views(org_id, world_id, scope).order_by("seq").stream()]

    def read_head(self, org_id: str, world_id: str) -> dict[str, Any]:
        data = self._head(org_id, world_id).get().to_dict() or {}
        return {"last_seq": data.get("last_seq", 0), "lease": data.get("lease"), "view_seq": data.get("view_seq", {})}

    def transact(self, org_id: str, world_id: str, fn: TransactFn) -> dict[str, Any]:
        from google.cloud import firestore

        head_ref = self._head(org_id, world_id)

        @firestore.transactional
        def _run(transaction: firestore.Transaction) -> dict[str, Any]:
            snapshot = head_ref.get(transaction=transaction)
            data = snapshot.to_dict() or {}
            head = {
                "last_seq": data.get("last_seq", 0),
                "lease": data.get("lease"),
                "view_seq": data.get("view_seq", {}),
            }
            new_head, event, views = fn(head)
            transaction.set(head_ref, new_head)
            if event is not None:
                transaction.create(self._events(org_id, world_id).document(f"{event['seq']:08d}"), event)
            for scope, doc in views:
                transaction.create(self._views(org_id, world_id, scope).document(f"{doc['seq']:08d}"), doc)
            return new_head

        return _run(self._client.transaction())
