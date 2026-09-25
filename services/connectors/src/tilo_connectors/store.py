"""tilo_connectors.store — InMemoryOutboxStore, the package's ready-made outbox store (a
Firestore-backed one ships later). No method here is part of the pinned API (tests/API.md):
only Outbox reads and writes it.

Trust boundary (services/connectors/CLAUDE.md): the mutators are underscored and share one lock,
so several tilo-connectors instances sharing this store (Cloud Run scales out) never both win a
state change or store two entries for one (world_id, idempotency_key). Claiming an entry to send,
and claiming the oldest pending data.transfer to emit, are both leases: only one instance holds
either at a time, taken over only once it expires. Marking an entry sent and recording its
pending transfer are one atomic write (PI-17), so a crash between them can never happen; the
transfer then lives here (a plain, insertion-ordered dict), not in one instance's memory, so any
instance can emit it later, exactly once, in send order.
"""

from __future__ import annotations

import threading
from copy import deepcopy

from ._time import add_seconds

_Lease = tuple[str, str]  # (holder, expiry)


def _try_claim(leases: dict[str, _Lease], key: str, holder: str, now: str, lease_seconds: float) -> bool:
    """True and records the lease, unless `key` is already leased to someone else and that
    lease has not yet expired."""
    held_by, expiry = leases.get(key, (None, None))
    if expiry is not None and now < expiry:
        return False
    leases[key] = (holder, add_seconds(now, lease_seconds))
    return True


def _release(leases: dict[str, _Lease], key: str, holder: str) -> None:
    """Gives up a lease early, only while `holder` still holds it."""
    if leases.get(key, (None,))[0] == holder:
        leases.pop(key, None)


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._send_leases: dict[str, _Lease] = {}
        self._transfer_leases: dict[str, _Lease] = {}
        self._pending_transfers: dict[str, dict] = {}  # outbox_id -> data.transfer, send order

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
        """Inserts only if neither its id nor its (world_id, idempotency_key) is already stored;
        never overwrites. Returns whether it inserted."""
        with self._lock:
            key = (entry["world_id"], entry["idempotency_key"])
            if entry["id"] in self._by_id or key in self._by_key:
                return False
            copied = deepcopy(entry)
            self._by_id[copied["id"]] = copied
            self._by_key[key] = copied["id"]
            return True

    def _compare_and_set_state(self, outbox_id: str, from_states: tuple[str, ...], to_state: str) -> dict | None:
        """Atomically moves the entry from one of from_states to to_state (cancel only)."""
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] not in from_states:
                return None
            entry["state"] = to_state
            return deepcopy(entry)

    def _claim_for_sending(self, outbox_id: str, holder: str, now: str, lease_seconds: float) -> dict | None:
        """Moves queued/scheduled to sending under a fresh lease, or takes over a sending entry
        whose lease has expired (its holder is presumed dead); otherwise refuses. Never two
        holders at once."""
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] not in ("queued", "scheduled", "sending"):
                return None
            if not _try_claim(self._send_leases, outbox_id, holder, now, lease_seconds):
                return None
            entry["state"] = "sending"
            return deepcopy(entry)

    def _finalize_claim(self, outbox_id: str, holder: str, to_state: str, transfer: dict | None = None) -> dict | None:
        """Moves sending to to_state, only while `holder` still holds the lease, and — in the
        same write — records `transfer` as pending (PI-17: never a sent entry with no transfer
        recorded, whatever crashes in between)."""
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] != "sending" or self._send_leases.get(outbox_id, (None,))[0] != holder:
                return None
            entry["state"] = to_state
            self._send_leases.pop(outbox_id, None)
            if transfer is not None:
                self._pending_transfers.setdefault(outbox_id, transfer)
            return deepcopy(entry)

    def _release_claim(self, outbox_id: str, holder: str) -> None:
        """An adapter Exception, not a crash — the process is still alive to let go: the entry
        stays "sending" but is immediately reclaimable, since making everyone wait out the full
        lease would serve no purpose."""
        with self._lock:
            _release(self._send_leases, outbox_id, holder)

    def _claim_oldest_pending_transfer(self, holder: str, now: str, lease_seconds: float) -> tuple[str, dict] | None:
        """The oldest data.transfer still pending, under a fresh lease — or None when there is
        none, or the oldest is leased to someone else, so a later one waits rather than jump the
        queue (send order)."""
        with self._lock:
            for outbox_id, transfer in self._pending_transfers.items():
                if not _try_claim(self._transfer_leases, outbox_id, holder, now, lease_seconds):
                    return None
                return (outbox_id, transfer)
            return None

    def _discard_pending_transfer(self, outbox_id: str, holder: str) -> None:
        """Removes a transfer for good once it has been emitted, only while `holder` still holds
        its lease."""
        with self._lock:
            if self._transfer_leases.get(outbox_id, (None,))[0] == holder:
                self._pending_transfers.pop(outbox_id, None)
                _release(self._transfer_leases, outbox_id, holder)

    def _release_pending_transfer_claim(self, outbox_id: str, holder: str) -> None:
        """emit raised: give up the lease (still pending, retried later) without discarding it."""
        with self._lock:
            _release(self._transfer_leases, outbox_id, holder)
