"""Firestore store for the beta-allowance feedback (BQ-FEEDBACK-1). It writes only under `orgs/{org}/feedback`:
`orgs/{org}/feedback/{uid}/items/{id}`, four fields each. One transaction reads the uid's own items (at most 20) and
then writes, so the hourly and lifetime limits hold under concurrency. The text is never logged."""

from __future__ import annotations

import os
import threading
import uuid
from typing import Any

from google.cloud import firestore

from tilo_api import deps, store_door
from tilo_api.feedback import AddResult, decide

_opened: dict[tuple[str | None, ...], Any] = {}
_lock = threading.Lock()
_CONFIG = (store_door.ENV_STORE, store_door.ENV_PROJECT, "FIRESTORE_EMULATOR_HOST", "GOOGLE_CLOUD_PROJECT", "K_SERVICE")


class FirestoreFeedbackStore:
    def __init__(self, client: Any, *, org_id: str = deps.ORG_ID) -> None:
        self._client, self._org_id = client, org_id

    def add(
        self, *, uid: str, text: str, context: str, created_at: str, hourly_limit: int, lifetime_limit: int
    ) -> AddResult:
        items = f"orgs/{self._org_id}/feedback/{uid}/items"
        ref = self._client.document(f"{items}/{uuid.uuid4().hex}")

        @firestore.transactional  # type: ignore[misc]
        def run(tx: Any) -> AddResult:
            mine = [
                (d.to_dict() or {}).get("created_at", created_at)
                for d in self._client.collection(items).stream(transaction=tx)
            ]
            outcome = decide(mine, created_at, hourly_limit, lifetime_limit)
            if outcome.status == "stored":
                tx.create(ref, {"uid": uid, "text": text, "created_at": created_at, "context": context})
            return outcome

        return run(self._client.transaction())


def open_feedback_store() -> FirestoreFeedbackStore:
    """The process's store for this config (never cached when refused); raises `ApiStoreNotConfigured`."""
    key = tuple(os.environ.get(name) for name in _CONFIG)
    with _lock:
        if key not in _opened:
            opened = store_door.open_api_store(firestore_client_factory=store_door.client_factory)
            _opened[key] = FirestoreFeedbackStore(opened.client)
        return _opened[key]
