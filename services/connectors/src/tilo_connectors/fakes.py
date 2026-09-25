"""tilo_connectors.fakes — in-process connector adapters for dev/CI (EFF-01): no network, no
real Google API, no real email ever. Public surface: tests/API.md."""

from __future__ import annotations

from .errors import MissingGrant
from .outbox import Grant


class FakeGmail:
    """Threads every reply into the given thread_id (destination) — a thread reply never
    becomes a new email (FR-CHN-13). Dedupes by (world, idempotency_key): OB-03 keys are unique
    per world only, not across worlds."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._by_key: dict[tuple[str, str], dict] = {}

    def send_reply(
        self, thread_id: str, item: dict | None, recipients: list[str], idempotency_key: str, grant: Grant
    ) -> dict:
        if not isinstance(grant, Grant):
            raise MissingGrant("send_reply requires a Grant minted by Outbox.dispatch_due()")
        grant.verify()
        key = (grant.world_id, idempotency_key)
        existing = self._by_key.get(key)
        if existing is not None:
            return existing  # OB-03: a key already recorded (in this world) is not sent again
        record = {
            "thread_id": thread_id,
            "item": item,
            "recipients": list(recipients),
            "idempotency_key": idempotency_key,
        }
        self._by_key[key] = record
        self.sent.append(record)
        return record
