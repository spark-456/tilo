"""Fresh-source guards for already scoped Autopilot ports (FR-MTG-08).

These do not dispatch, authorise, or replace inner scope/policy checks. The factory
must also pass the hook into durable adapters; delegation is not a transaction.
"""

from collections.abc import Callable

from tilo_channels.autopilot_state import CardStore, Outbox, StopQueue


class PublicationCards:
    def __init__(self, inner: CardStore, check: Callable[[], None]) -> None:
        self._inner, self._check = inner, check

    def get(self, user_id: str, key: str) -> dict | None:
        self._check()
        return self._inner.get(user_id, key)

    def create(self, user_id: str, key: str, value: dict) -> bool:
        self._check()
        return self._inner.create(user_id, key, value)

    def put(self, user_id: str, key: str, value: dict) -> None:
        self._check()
        return self._inner.put(user_id, key, value)


class PublicationStops:
    def __init__(self, inner: StopQueue, check: Callable[[], None]) -> None:
        self._inner, self._check = inner, check

    def add(self, user_id: str, card_id: str) -> None:
        self._check()
        return self._inner.add(user_id, card_id)

    def pending(self) -> list[tuple[str, str]]:
        self._check()
        return self._inner.pending()

    def remove(self, user_id: str, card_id: str) -> None:
        self._check()
        return self._inner.remove(user_id, card_id)


class PublicationOutbox:
    def __init__(self, inner: Outbox, check: Callable[[], None]) -> None:
        self._inner, self._check = inner, check

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        self._check()
        return self._inner.enqueue(entry, evidence)

    def cancel(self, outbox_id: str) -> dict:
        self._check()
        return self._inner.cancel(outbox_id)

    def get(self, outbox_id: str) -> dict | None:
        self._check()
        return self._inner.get(outbox_id)

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        self._check()
        return self._inner.get_by_idempotency_key(world_id, idempotency_key)

    def revoke(self, world_id: str, idempotency_key: str) -> dict | None:
        self._check()
        return self._inner.revoke(world_id, idempotency_key)
