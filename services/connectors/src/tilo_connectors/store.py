"""tilo_connectors.store — InMemoryOutboxStore. tests/API.md "Store"; mutators are underscored."""

from __future__ import annotations

import threading
from copy import deepcopy

from ._time import add_seconds

_Lease = tuple[str, str]  # (holder, expiry)


def _try_claim(leases: dict[str, _Lease], key: str, holder: str, now: str, lease_seconds: float) -> bool:
    expiry = leases.get(key, (None, None))[1]  # None or already expired: claimable
    if expiry is not None and now < expiry:
        return False
    leases[key] = (holder, add_seconds(now, lease_seconds))
    return True


def _release(leases: dict[str, _Lease], key: str, holder: str) -> None:  # only while holder still holds it
    if leases.get(key, (None,))[0] == holder:
        leases.pop(key, None)


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._send_leases: dict[str, _Lease] = {}
        self._transfer_leases: dict[str, _Lease] = {}
        self._pending_transfers: dict[str, tuple[str, dict]] = {}  # outbox_id -> (world_id, transfer)

    def get(self, outbox_id: str | None) -> dict | None:
        with self._lock:
            return deepcopy(self._by_id.get(outbox_id)) if outbox_id is not None else None

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        return self.get(self._by_key.get((world_id, idempotency_key)))

    def all_entries(self) -> list[dict]:
        with self._lock:
            return [deepcopy(entry) for entry in self._by_id.values()]

    def _insert_if_absent(self, entry: dict) -> bool:  # OB-03: neither id nor key already stored
        with self._lock:
            key = (entry["world_id"], entry["idempotency_key"])
            if entry["id"] in self._by_id or key in self._by_key:
                return False
            copied = deepcopy(entry)
            self._by_id[copied["id"]] = copied
            self._by_key[key] = copied["id"]
            return True

    def _cancel(self, outbox_id: str) -> dict | None:  # scheduled -> cancelled, for Outbox.cancel
        with self._lock:
            if (entry := self._by_id.get(outbox_id)) is None or entry["state"] != "scheduled":
                return None
            entry["state"] = "cancelled"
            return deepcopy(entry)

    def _claim_for_sending(self, outbox_id: str, holder: str, now: str, lease_seconds: float) -> dict | None:
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] not in ("queued", "scheduled", "sending"):
                return None
            if not _try_claim(self._send_leases, outbox_id, holder, now, lease_seconds):
                return None
            entry["state"] = "sending"  # takes over an expired lease too
            return deepcopy(entry)

    def _finalize_claim(self, outbox_id: str, holder: str, to_state: str, transfer: dict | None = None) -> dict | None:
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] != "sending" or self._send_leases.get(outbox_id, (None,))[0] != holder:
                return None
            entry["state"] = to_state  # + pending transfer, same write (PI-17)
            _release(self._send_leases, outbox_id, holder)
            if transfer is not None:
                self._pending_transfers.setdefault(outbox_id, (entry["world_id"], deepcopy(transfer)))
            return deepcopy(entry)

    def _release_lease(self, kind: str, outbox_id: str, holder: str) -> None:  # kind: "send"/"transfer"
        with self._lock:
            _release(self._send_leases if kind == "send" else self._transfer_leases, outbox_id, holder)

    def _claim_oldest_pending_transfer(
        self, holder: str, now: str, lease_seconds: float, exclude: frozenset[str] = frozenset()
    ) -> tuple[str, str, dict] | None:  # oldest pending transfer of a world not in `exclude`
        with self._lock:
            seen_worlds = set(exclude)
            for outbox_id, (world_id, transfer) in self._pending_transfers.items():
                if world_id in seen_worlds:
                    continue
                seen_worlds.add(world_id)
                if _try_claim(self._transfer_leases, outbox_id, holder, now, lease_seconds):
                    return (outbox_id, world_id, deepcopy(transfer))  # a mutating emit never corrupts a retry
            return None

    def _discard_pending_transfer(self, outbox_id: str, holder: str) -> None:  # always removed once delivered
        with self._lock:
            self._pending_transfers.pop(outbox_id, None)
            _release(self._transfer_leases, outbox_id, holder)
