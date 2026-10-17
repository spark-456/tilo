"""Owner-scoped memory items (ADR-0049 MI-01/02/09)."""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from tilo_policy.schemas import conforms

_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}\Z")
_USER = re.compile(r"u_[0-9A-Za-z_]{1,48}\Z")
_ID = re.compile(r"mem_[0-9A-Za-z_]{1,48}\Z")


class MemoryFull(Exception):
    """The owner's 100-item limit was reached."""


class MemoryStoreError(Exception):
    """A stored item or backing store failed closed."""


def _key(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip().casefold()


def _item(org: str, owner: str, text: str, kind: str, source: str, now: str) -> dict[str, Any]:
    item = {
        "id": f"mem_{uuid4().hex}",
        "org_id": org,
        "owner": owner,
        "text": text.strip(),
        "kind": kind,
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    if not conforms("memory_item.schema.json", item):
        raise MemoryStoreError("invalid item")
    return item


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[tuple[str, str, str], dict[str, Any]] = {}

    def list(self, org: str, owner: str) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(
                (dict(v) for (o, u, _), v in self._items.items() if o == org and u == owner),
                key=lambda v: (-_stamp(v["updated_at"]), v["id"]),
            )

    def get(self, org: str, owner: str, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._items.get((org, owner, item_id))
            return dict(item) if item else None

    def create(self, org: str, owner: str, text: str, kind: str, source: str, now: str) -> tuple[dict[str, Any], bool]:
        with self._lock:
            items = self.list(org, owner)
            duplicate = next((v for v in items if _key(v["text"]) == _key(text)), None)
            if duplicate:
                return duplicate, False
            if len(items) >= 100:
                raise MemoryFull
            item = _item(org, owner, text, kind, source, now)
            self._items[(org, owner, item["id"])] = item
            return dict(item), True

    def update(self, org: str, owner: str, item_id: str, changes: dict[str, Any], now: str) -> dict[str, Any] | None:
        with self._lock:
            old = self._items.get((org, owner, item_id))
            if old is None:
                return None
            item = {**old, **changes, "updated_at": now}
            if not conforms("memory_item.schema.json", item):
                raise MemoryStoreError("invalid item")
            self._items[(org, owner, item_id)] = item
            return dict(item)

    def delete(self, org: str, owner: str, item_id: str) -> bool:
        with self._lock:
            return self._items.pop((org, owner, item_id), None) is not None

    def erase(self, owner: str) -> int:
        with self._lock:
            keys = [key for key in self._items if key[1] == owner]
            for key in keys:
                del self._items[key]
            return len(keys)

    def count_owner(self, owner: str) -> int:
        with self._lock:
            return sum(key[1] == owner for key in self._items)


def _stamp(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


class FirestoreMemoryStore:
    """One collection per owner; duplicate check and 100 cap share a transaction."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def _collection(self, org: str, owner: str) -> Any:
        if not (_ORG.fullmatch(org) and _USER.fullmatch(owner)):
            raise MemoryStoreError("invalid address")
        return self.client.collection(f"orgs/{org}/users/{owner}/memory")

    def _ref(self, org: str, owner: str, item_id: str) -> Any:
        self._collection(org, owner)  # validate the address before building a document path
        if not _ID.fullmatch(item_id):
            raise MemoryStoreError("invalid item id")
        return self.client.document(f"orgs/{org}/users/{owner}/memory/{item_id}")

    def _meta(self, org: str, owner: str) -> Any:
        self._collection(org, owner)
        return self.client.document(f"orgs/{org}/users/{owner}/memory_meta/state")

    @staticmethod
    def _checked(snap: Any, org: str, owner: str) -> dict[str, Any]:
        item = snap.to_dict()
        if not conforms("memory_item.schema.json", item) or item["org_id"] != org or item["owner"] != owner:
            raise MemoryStoreError("invalid stored item")
        return item

    def list(self, org: str, owner: str) -> list[dict[str, Any]]:
        return sorted(
            (self._checked(s, org, owner) for s in self._collection(org, owner).stream()),
            key=lambda v: (-_stamp(v["updated_at"]), v["id"]),
        )

    def get(self, org: str, owner: str, item_id: str) -> dict[str, Any] | None:
        if not item_id.startswith("mem_"):
            return None
        snap = self._ref(org, owner, item_id).get()
        return self._checked(snap, org, owner) if snap.exists else None

    def create(self, org: str, owner: str, text: str, kind: str, source: str, now: str) -> tuple[dict[str, Any], bool]:
        from google.cloud import firestore

        coll = self._collection(org, owner)
        meta = self._meta(org, owner)

        @firestore.transactional
        def write(tx: Any) -> tuple[dict[str, Any], bool]:
            held = meta.get(transaction=tx)
            items = [self._checked(s, org, owner) for s in coll.stream(transaction=tx)]
            duplicate = next((v for v in items if _key(v["text"]) == _key(text)), None)
            if duplicate:
                return duplicate, False
            if len(items) >= 100:
                raise MemoryFull
            item = _item(org, owner, text, kind, source, now)
            next_meta = {"count": len(items) + 1, "rev": (held.to_dict()["rev"] if held.exists else 0) + 1}
            if held.exists:
                tx.set(meta, next_meta)
            else:
                tx.create(meta, next_meta)
            tx.create(self._ref(org, owner, item["id"]), item)
            return item, True

        return write(self.client.transaction())

    def update(self, org: str, owner: str, item_id: str, changes: dict[str, Any], now: str) -> dict[str, Any] | None:
        from google.cloud import firestore

        ref = self._ref(org, owner, item_id)

        @firestore.transactional
        def write(tx: Any) -> dict[str, Any] | None:
            snap = ref.get(transaction=tx)
            if not snap.exists:
                return None
            item = {**self._checked(snap, org, owner), **changes, "updated_at": now}
            if not conforms("memory_item.schema.json", item):
                raise MemoryStoreError("invalid item")
            tx.set(ref, item)
            return item

        return write(self.client.transaction())

    def delete(self, org: str, owner: str, item_id: str) -> bool:
        from google.cloud import firestore

        ref, meta = self._ref(org, owner, item_id), self._meta(org, owner)

        @firestore.transactional
        def remove(tx: Any) -> bool:
            item, held = ref.get(transaction=tx), meta.get(transaction=tx)
            if not item.exists:
                return False
            tx.delete(ref)
            if held.exists:
                data = held.to_dict()
                tx.set(meta, {"count": max(0, data["count"] - 1), "rev": data["rev"] + 1})
            return True

        return remove(self.client.transaction())


@dataclass(frozen=True)
class _ErasureRecord:
    entity: str
    record_id: str
    created_at: datetime
    user_id: str


class MemoryErasureStore:
    """FR-MEM-09 registry adapter: fresh metadata reads, no note text in reports."""

    def __init__(self, store: InMemoryMemoryStore | FirestoreMemoryStore) -> None:
        self.store = store

    def records(self) -> list[_ErasureRecord]:
        if isinstance(self.store, InMemoryMemoryStore):
            with self.store._lock:
                rows = [dict(v) for v in self.store._items.values()]
        else:
            rows = [s.to_dict() for s in self.store.client.collection_group("memory").stream()]
        if any(not conforms("memory_item.schema.json", v) for v in rows):
            raise MemoryStoreError("invalid stored item")
        return [
            _ErasureRecord(
                "memory_item",
                f"orgs/{v['org_id']}/users/{v['owner']}/memory/{v['id']}",
                datetime.fromisoformat(v["created_at"].replace("Z", "+00:00")),
                v["owner"],
            )
            for v in rows
        ]

    def delete(self, record_id: str) -> None:
        parts = record_id.split("/")
        if len(parts) != 6 or parts[0] != "orgs" or parts[2] != "users" or parts[4] != "memory":
            raise MemoryStoreError("invalid erasure id")
        self.store.delete(parts[1], parts[3], parts[5])
