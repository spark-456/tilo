"""tilo_connectors.store — InMemoryOutboxStore, the package's ready-made outbox store (a
Firestore-backed one ships later). No method here is part of the pinned API (tests/API.md):
only Outbox reads and writes it.

Trust boundary (services/connectors/CLAUDE.md): the mutators are underscored and share one lock,
so several tilo-connectors instances sharing this store (Cloud Run scales out) never both win a
state change or store two entries for one (world_id, idempotency_key); a claim to send is a
lease, taken over only once it expires, so an in-flight send is never claimed twice. A
data.transfer not yet emitted lives here too (a plain, insertion-ordered dict), not in one
instance's memory, so any instance can emit it later, exactly once, in send order.
"""

from __future__ import annotations

import threading
from copy import deepcopy

from ._time import add_seconds


class InMemoryOutboxStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._leases: dict[str, tuple[str, str]] = {}  # outbox_id -> (holder, lease_expiry)
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
            if entry is None:
                return None
            state = entry["state"]
            if state == "sending":
                _holder, expiry = self._leases.get(outbox_id, (None, None))
                if expiry is not None and now < expiry:
                    return None  # still leased to someone else
            elif state not in ("queued", "scheduled"):
                return None
            entry["state"] = "sending"
            self._leases[outbox_id] = (holder, add_seconds(now, lease_seconds))
            return deepcopy(entry)

    def _finalize_claim(self, outbox_id: str, holder: str, to_state: str) -> dict | None:
        """Moves sending to to_state, only while `holder` still holds the lease (nobody else has
        taken it over)."""
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] != "sending" or self._leases.get(outbox_id, (None,))[0] != holder:
                return None
            entry["state"] = to_state
            self._leases.pop(outbox_id, None)
            return deepcopy(entry)

    def _release_claim(self, outbox_id: str, holder: str) -> None:
        """Gives up a claim early (an adapter Exception, not a crash — the process is still
        alive to let go): the entry stays "sending" but is immediately reclaimable, since making
        everyone wait out the full lease would serve no purpose."""
        with self._lock:
            if self._leases.get(outbox_id, (None,))[0] == holder:
                self._leases.pop(outbox_id, None)

    def _add_pending_transfer(self, outbox_id: str, transfer: dict) -> None:
        with self._lock:
            self._pending_transfers.setdefault(outbox_id, transfer)

    def _discard_pending_transfer(self, outbox_id: str) -> None:
        with self._lock:
            self._pending_transfers.pop(outbox_id, None)

    def _pending_transfers_snapshot(self) -> list[tuple[str, dict]]:
        with self._lock:
            return list(self._pending_transfers.items())
