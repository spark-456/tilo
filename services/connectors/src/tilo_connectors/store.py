"""tilo_connectors.store — InMemoryOutboxStore, the package's ready-made outbox store (a
Firestore-backed one ships later). No method here is part of the pinned API (tests/API.md):
only Outbox reads and writes it."""

from __future__ import annotations

from copy import deepcopy


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._by_id: dict[str, dict] = {}
        self._by_key: dict[tuple[str, str], str] = {}

    def get(self, outbox_id: str) -> dict | None:
        entry = self._by_id.get(outbox_id)
        return deepcopy(entry) if entry is not None else None

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        outbox_id = self._by_key.get((world_id, idempotency_key))
        return self.get(outbox_id) if outbox_id is not None else None

    def put(self, entry: dict) -> None:
        """Inserts or overwrites the entry named by entry["id"], independent of the caller's dict."""
        copied = deepcopy(entry)
        self._by_id[copied["id"]] = copied
        self._by_key[(copied["world_id"], copied["idempotency_key"])] = copied["id"]

    def all_entries(self) -> list[dict]:
        return [deepcopy(entry) for entry in self._by_id.values()]
