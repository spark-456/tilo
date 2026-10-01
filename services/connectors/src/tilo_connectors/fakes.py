"""tilo_connectors.fakes — in-process connector adapters for dev/CI (EFF-01). tests/API.md."""

from __future__ import annotations

import threading

from .errors import MissingGrant
from .outbox import Grant


class FakeGmail:  # FR-CHN-13, OB-03: threads the reply, dedupes by (world, key), atomically
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._by_key: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    def send_reply(
        self, thread_id: str, item: dict | None, recipients: list[str], idempotency_key: str, grant: Grant
    ) -> dict:
        if not isinstance(grant, Grant):
            raise MissingGrant("send_reply requires a Grant minted by Outbox.dispatch_due()")
        grant.verify(idempotency_key)
        key = (grant.world_id, idempotency_key)
        with self._lock:
            if (existing := self._by_key.get(key)) is not None:
                return existing
            record = {
                "thread_id": thread_id,
                "item": item,
                "recipients": list(recipients),
                "idempotency_key": idempotency_key,
            }
            self._by_key[key] = record
            self.sent.append(record)
            return record
