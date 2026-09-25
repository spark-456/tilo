"""tilo_connectors.store — InMemoryOutboxStore, the package's ready-made outbox store (a
Firestore-backed one ships later). No method here is part of the pinned API (tests/API.md):
only Outbox reads and writes it.

Trust boundary (services/connectors/CLAUDE.md): the two mutators are underscored and hold their
own lock, so two Outbox instances sharing one store (a cancel racing a dispatch) never both win
a state change — the store, not the caller, is what makes each transition atomic.
"""

from __future__ import annotations

import threading
from copy import deepcopy


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._by_key: dict[tuple[str, str], str] = {}

    def get(self, outbox_id: str) -> dict | None:
        with self._lock:
            entry = self._by_id.get(outbox_id)
            return deepcopy(entry) if entry is not None else None

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        with self._lock:
            outbox_id = self._by_key.get((world_id, idempotency_key))
            entry = self._by_id.get(outbox_id) if outbox_id is not None else None
            return deepcopy(entry) if entry is not None else None

    def all_entries(self) -> list[dict]:
        with self._lock:
            return [deepcopy(entry) for entry in self._by_id.values()]

    def _insert_if_absent(self, entry: dict) -> bool:
        """Inserts entry only if its id is not already stored; never overwrites. Returns
        whether it inserted."""
        with self._lock:
            if entry["id"] in self._by_id:
                return False
            copied = deepcopy(entry)
            self._by_id[copied["id"]] = copied
            self._by_key[(copied["world_id"], copied["idempotency_key"])] = copied["id"]
            return True

    def _compare_and_set_state(self, outbox_id: str, from_states: tuple[str, ...], to_state: str) -> dict | None:
        """Atomically moves the entry from one of from_states to to_state; returns the updated
        entry, or None if it does not exist or is no longer in one of from_states (someone else
        already moved it)."""
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] not in from_states:
                return None
            entry["state"] = to_state
            return deepcopy(entry)
