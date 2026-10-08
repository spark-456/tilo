"""Firestore store for the beta-allowance feedback (BQ-FEEDBACK-1). It writes only under `orgs/{org}/feedback`:
`orgs/{org}/feedback/{uid}/items/{slot}` with fixed slot ids `00`..`19`, four fields each. A write is a `create` of
the first free slot, so a rival that took the same slot makes it fail (`AlreadyExists`), and the retry re-reads: the
hourly and lifetime limits hold under concurrency whatever the database's lock mode. The read is bounded to
`lifetime_limit + 1` documents. After its retries it raises `FeedbackBusy`. The text is never logged."""

from __future__ import annotations

import os
import threading
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import firestore

from tilo_api import deps, store_door
from tilo_api.feedback import AddResult, FeedbackBusy, decide

_opened: dict[tuple[str | None, ...], Any] = {}
_lock = threading.Lock()
_CONFIG = (store_door.ENV_STORE, store_door.ENV_PROJECT, "FIRESTORE_EMULATOR_HOST", "GOOGLE_CLOUD_PROJECT", "K_SERVICE")
_ATTEMPTS = 5


class FirestoreFeedbackStore:
    def __init__(self, client: Any, *, org_id: str = deps.ORG_ID) -> None:
        self._client, self._org_id = client, org_id

    def add(
        self, *, uid: str, text: str, context: str, created_at: str, hourly_limit: int, lifetime_limit: int
    ) -> AddResult:
        items = f"orgs/{self._org_id}/feedback/{uid}/items"

        @firestore.transactional  # type: ignore[misc]
        def run(tx: Any) -> AddResult:
            held = {
                d.id: (d.to_dict() or {}).get("created_at", created_at)
                for d in self._client.collection(items).limit(lifetime_limit + 1).stream(transaction=tx)
            }
            outcome = decide(list(held.values()), created_at, hourly_limit, lifetime_limit)
            if outcome.status == "stored":
                slot = next(f"{n:02d}" for n in range(lifetime_limit) if f"{n:02d}" not in held)
                tx.create(
                    self._client.document(f"{items}/{slot}"),
                    {"uid": uid, "text": text, "created_at": created_at, "context": context},
                )
            return outcome

        for _ in range(_ATTEMPTS):
            try:
                return run(self._client.transaction())
            except (gexc.AlreadyExists, gexc.Aborted):
                continue  # a rival took the slot: read again
            except ValueError as exc:  # the library's "failed in N attempts" wraps the Aborted it gave up on
                if not isinstance(exc.__cause__, gexc.Aborted):
                    raise
        raise FeedbackBusy


def open_feedback_store() -> FirestoreFeedbackStore:
    """The process's store for this config (never cached when refused); raises `ApiStoreNotConfigured`."""
    key = tuple(os.environ.get(name) for name in _CONFIG)
    with _lock:
        if key not in _opened:
            opened = store_door.open_api_store(firestore_client_factory=store_door.client_factory)
            _opened[key] = FirestoreFeedbackStore(opened.client)
        return _opened[key]
