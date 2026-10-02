"""tilo_connectors.outbox — the only path to a side effect (SEC-03). Full behaviour: tests/API.md."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import tilo_policy

from ._schema import outbox_validator
from ._time import add_seconds
from .errors import MissingGrant, OutboxRefused, SideEffectRefused
from .registry import RESERVED_CONNECTOR_ID
from .store import InMemoryOutboxStore

_ALWAYS_DUE_STATES = ("queued", "sending")  # "scheduled" also once scheduled_at <= now
_LEASE_SECONDS = 30  # generous next to any real adapter/emit call
_LIVE_GRANTS: set[int] = set()  # ids of Grants a send is currently authorised for (SEC-03)


def _transfer_event(entry: dict) -> dict:  # PI-16/17: "out", this id, authz and item unchanged
    return {
        "type": "data.transfer",
        "authz": deepcopy(entry["authz"]),
        "data": {
            "connector": entry["connector"],
            "action_type": entry["action_type"],
            "direction": "out",
            "artifact": deepcopy(entry["item"]),  # independent of entry from the moment it's built
            "outbox_id": entry["id"],
            "risk_tier": entry["risk_tier"],
        },
    }


@dataclass(frozen=True)
class Grant:  # SEC-03: minted only by dispatch_due(); validity is object identity, not fields
    world_id: str
    idempotency_key: str

    def verify(self, idempotency_key: str) -> None:
        if id(self) not in _LIVE_GRANTS or self.idempotency_key != idempotency_key:
            raise MissingGrant("grant not minted by Outbox.dispatch_due() for this exact send")


class Outbox:
    def __init__(
        self,
        store: InMemoryOutboxStore,
        connectors: dict[str, Any],
        emit: Callable[[dict], None],
        clock: Callable[[], str],
    ) -> None:
        if any(name.strip() == RESERVED_CONNECTOR_ID for name in connectors):
            raise ValueError(f"connector id {RESERVED_CONNECTOR_ID!r} is reserved and cannot be bound")
        self._store = store
        self._connectors = connectors
        self._emit = emit
        self._clock = clock

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        if errors := sorted(outbox_validator().iter_errors(entry), key=lambda e: list(e.path)):
            raise OutboxRefused(f"OB-05: {errors[0].message}")
        self._check_fresh_state(entry)
        if (existing := self._existing_or_conflict(entry)) is not None:
            return existing
        snapshot = deepcopy(entry)  # before check_entry: a caller mutating entry afterwards changes nothing
        case = {**deepcopy(evidence), "entry": deepcopy(snapshot), "transfer": None, "rule": None}
        if (verdict := tilo_policy.check_entry(case)) is not None:
            raise OutboxRefused(f"{verdict}: entry is not authorised")
        if self._store._insert_if_absent(snapshot):
            return deepcopy(snapshot)
        winner = self._existing_or_conflict(entry)  # lost a race with a concurrent enqueue
        assert winner is not None
        return winner

    def _existing_or_conflict(self, entry: dict) -> dict | None:
        if (existing := self._store.get_by_idempotency_key(entry["world_id"], entry["idempotency_key"])) is not None:
            return existing
        if self._store.get(entry["id"]) is not None:
            raise OutboxRefused(f"id {entry['id']!r} already stored under a different idempotency_key")
        return None

    def _check_fresh_state(self, entry: dict) -> None:  # OB-02: fresh state must match undo_window_s
        undo_window_s = entry["undo_window_s"]
        expected_state = "queued" if undo_window_s == 0 else "scheduled"
        if entry["state"] != expected_state:
            raise OutboxRefused(f"OB-02: a new entry must be {expected_state!r}, got {entry['state']!r}")
        try:
            expected_scheduled_at = add_seconds(entry["created_at"], undo_window_s)
        except (ValueError, TypeError, OverflowError) as exc:
            raise OutboxRefused(f"OB-02: cannot compute scheduled_at: {exc}") from exc
        if entry["scheduled_at"] != expected_scheduled_at:
            raise OutboxRefused(f"OB-02: bad scheduled_at, expected {expected_scheduled_at!r}")

    def cancel(self, outbox_id: str) -> dict:
        if (updated := self._store._cancel(outbox_id)) is None:
            raise OutboxRefused(f"cannot cancel {outbox_id!r}: not 'scheduled'")
        return updated

    def dispatch_due(self) -> list[dict]:
        now = self._clock()
        settled = [self._dispatch_one(e["id"]) for e in self._store.all_entries() if self._is_due(e, now)]
        self._flush_pending_transfers()
        return [entry for entry in settled if entry is not None]

    @staticmethod
    def _is_due(entry: dict, now: str) -> bool:
        state = entry["state"]
        if state in _ALWAYS_DUE_STATES:
            return True
        return state == "scheduled" and entry["scheduled_at"] <= now

    def _dispatch_one(self, outbox_id: str) -> dict | None:
        holder = uuid.uuid4().hex
        if (claimed := self._store._claim_for_sending(outbox_id, holder, self._clock(), _LEASE_SECONDS)) is None:
            return None
        name = claimed["connector"]
        adapter = None if name.strip() == RESERVED_CONNECTOR_ID else self._connectors.get(name)
        if adapter is None:  # never a reserved id, even if the map was edited after construction
            return self._store._finalize_claim(outbox_id, holder, "failed")
        grant = Grant(world_id=claimed["world_id"], idempotency_key=claimed["idempotency_key"])
        _LIVE_GRANTS.add(id(grant))
        execute = getattr(adapter, "execute_side_effect", None)  # FR-CON-04/05 adapters; else send_reply
        try:  # copies: a mutating adapter never touches what _transfer_event reads back below
            if execute is not None:
                execute(deepcopy(claimed), grant)
            else:
                adapter.send_reply(
                    claimed["destination"],
                    deepcopy(claimed["item"]),
                    deepcopy(claimed["recipients"]),
                    claimed["idempotency_key"],
                    grant,
                )
        except SideEffectRefused:  # final: it can never succeed as written; nothing is emitted
            return self._store._finalize_claim(outbox_id, holder, "failed")
        except BaseException as exc:  # ambiguous: release the lease; swallow only a plain Exception
            self._store._release_lease("send", outbox_id, holder)
            if isinstance(exc, Exception):
                return None
            raise
        finally:
            _LIVE_GRANTS.discard(id(grant))
        return self._store._finalize_claim(outbox_id, holder, "sent", _transfer_event(claimed))  # PI-17, atomic

    def _flush_pending_transfers(self) -> None:  # only emit path, oldest-first per world_id
        blocked_worlds: set[str] = set()
        while True:
            holder = uuid.uuid4().hex
            claim = self._store._claim_oldest_pending_transfer(
                holder, self._clock(), _LEASE_SECONDS, exclude=frozenset(blocked_worlds)
            )
            if claim is None:
                return
            outbox_id, world_id, transfer = claim
            try:
                self._emit(transfer)
            except Exception:
                self._store._release_lease("transfer", outbox_id, holder)
                blocked_worlds.add(world_id)
                continue
            self._store._discard_pending_transfer(outbox_id, holder)
