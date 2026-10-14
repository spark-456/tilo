"""tilo_connectors.store — InMemoryOutboxStore. tests/API.md "Store"; mutators are underscored."""

from __future__ import annotations

import threading
from collections.abc import Callable
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
    def __init__(self, clock: Callable[[], str] | None = None) -> None:
        self._clock = clock  # set: claims compare against this time, not the caller's (Firestore: server time)
        self._lock = threading.Lock()
        self._by_id: dict[str, dict] = {}
        self._by_key: dict[tuple[str, str], str] = {}
        self._send_leases: dict[str, _Lease] = {}
        self._abandoned_before_dispatch: set[str] = set()
        self._transfer_leases: dict[str, _Lease] = {}
        self._pending_transfers: dict[str, tuple[str, dict]] = {}  # outbox_id -> (world_id, transfer)
        self._pending_alerts: dict[str, tuple[str, dict]] = {}  # outbox_id -> (world_id, alert part)
        self._retries: dict[str, dict] = {}  # id -> retry_state(); store-side, never in the contract entry
        self._alerted: set[str] = set()  # outbox ids whose alert.raised is already written: once per entry
        self._revoked: set[tuple[str, str]] = set()  # (world_id, key) never to be created; never pruned (CHN-GATE-A)

    def get(self, outbox_id: str | None) -> dict | None:
        with self._lock:
            return deepcopy(self._by_id.get(outbox_id)) if outbox_id is not None else None

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        return self.get(self._by_key.get((world_id, idempotency_key)))

    def all_entries(self) -> list[dict]:
        with self._lock:
            return [deepcopy(entry) for entry in self._by_id.values()]

    def retry_state(self, outbox_id: str) -> dict:  # attempts, not_before, since (first failure), ambiguous
        with self._lock:
            return {
                "attempts": 0,
                "not_before": "",
                "since": None,
                "ambiguous": False,
                **self._retries.get(outbox_id, {}),
            }

    def _insert_if_absent(self, entry: dict) -> bool:  # OB-03: neither id nor key already stored
        with self._lock:
            key = (entry["world_id"], entry["idempotency_key"])
            if entry["id"] in self._by_id or key in self._by_key or key in self._revoked:
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

    def _revoke(self, world_id: str, idempotency_key: str) -> dict | None:  # for Outbox.revoke; never creates an entry
        with self._lock:
            if (outbox_id := self._by_key.get((world_id, idempotency_key))) is None:
                self._revoked.add((world_id, idempotency_key))  # _insert_if_absent refuses the key from now on
                return None
            entry = self._by_id[outbox_id]
            if entry["state"] == "scheduled":
                entry["state"] = "cancelled"
            return deepcopy(entry)

    def _abandon(
        self, outbox_id: str, now: str, keep_ambiguous: bool = False
    ) -> dict | None:  # unsent, no live lease -> failed, for Outbox.abandon
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] not in ("queued", "scheduled", "sending"):
                return None
            expiry = self._send_leases.get(outbox_id, (None, None))[1]
            if expiry is not None and now < expiry:
                return None
            if keep_ambiguous and (self._retries.get(outbox_id, {}).get("ambiguous") or expiry is not None):
                return None  # it may have gone out (a lost answer, or a lease nobody released): decided under this lock
            entry["state"] = "failed"
            self._retries.pop(outbox_id, None)
            return deepcopy(entry)

    def _abandon_before_dispatch(self, outbox_id: str) -> dict | None:
        # A terminal failure or any prior dispatch lease is never proof that nothing was sent.
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if (
                entry is None
                or entry["state"] not in ("queued", "scheduled")
                or outbox_id in self._send_leases
                or outbox_id in self._retries
            ):
                return None
            entry["state"] = "failed"
            self._abandoned_before_dispatch.add(outbox_id)
            return deepcopy(entry)

    def was_abandoned_before_dispatch(self, outbox_id: str) -> bool:
        with self._lock:
            return outbox_id in self._abandoned_before_dispatch

    def _cancel_source(self, outbox_id: str, now: str, alert: dict) -> dict | None:
        """X-SEC37-FU4b: refuse live leases; preserve uncertainty and alert while stopping resend."""
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] not in ("queued", "scheduled", "sending"):
                return None
            expiry = self._send_leases.get(outbox_id, (None, None))[1]
            if expiry is not None and now < expiry:
                return None
            ambiguous = bool(self._retries.get(outbox_id, {}).get("ambiguous") or expiry is not None)
            entry["state"] = "failed"
            self._send_leases.pop(outbox_id, None)
            if ambiguous:
                self._retries[outbox_id] = {**self._retries.get(outbox_id, {}), "ambiguous": True}
                self._record_alert(outbox_id, entry["world_id"], alert)
            else:
                self._retries.pop(outbox_id, None)
            return deepcopy(entry)

    def _claim_for_sending(
        self, outbox_id: str, holder: str, now: str, lease_seconds: float, skew_s: float = 0
    ) -> dict | None:  # never before scheduled_at + skew_s (PI-12) or the entry's not-before
        with self._lock:
            now = self._clock() if self._clock is not None else now
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] not in ("queued", "scheduled", "sending"):
                return None
            if entry.get("undo_window_s") and "scheduled_at" in entry:
                if now < add_seconds(entry["scheduled_at"], skew_s):
                    return None
            if now < self._retries.get(outbox_id, {}).get("not_before", ""):  # not before the next attempt
                return None
            had_lease = outbox_id in self._send_leases  # still here only if it expired unreleased
            if not _try_claim(self._send_leases, outbox_id, holder, now, lease_seconds):
                return None
            if had_lease:  # the earlier holder never said how it ended: it may have sent
                self._retries[outbox_id] = {**self._retries.get(outbox_id, {}), "ambiguous": True}
            entry["state"] = "sending"  # takes over an expired lease too
            return deepcopy(entry)

    def _finalize_claim(
        self, outbox_id: str, holder: str, to_state: str, transfer: dict | None = None, alert: dict | None = None
    ) -> dict | None:
        with self._lock:
            entry = self._by_id.get(outbox_id)
            if entry is None or entry["state"] != "sending" or self._send_leases.get(outbox_id, (None,))[0] != holder:
                return None
            entry["state"] = to_state  # + pending transfer or alert, same write (PI-17, FR-AGT-13)
            _release(self._send_leases, outbox_id, holder)
            self._retries.pop(outbox_id, None)
            if transfer is not None:
                self._pending_transfers.setdefault(outbox_id, (entry["world_id"], deepcopy(transfer)))
            self._record_alert(outbox_id, entry["world_id"], alert)
            return deepcopy(entry)

    def _record_alert(self, outbox_id: str, world_id: str, alert: dict | None) -> None:  # under the lock; once
        if alert is not None and outbox_id not in self._alerted:
            self._alerted.add(outbox_id)
            self._pending_alerts[outbox_id] = (world_id, deepcopy(alert))

    def _defer(
        self, outbox_id: str, holder: str, attempts: int, now: str, delay_s: float, ambiguous: bool = False,
        alert: dict | None = None,
    ) -> None:  # fmt: skip
        """Releases holder's send lease; no attempt before now + delay_s (store time when the store has a clock)."""
        with self._lock:
            now = self._clock() if self._clock is not None else now
            entry = self._by_id.get(outbox_id)
            if entry is None or self._send_leases.get(outbox_id, (None,))[0] != holder:
                return
            since = self._retries.get(outbox_id, {}).get("since") or now
            not_before = add_seconds(now, delay_s)
            self._retries[outbox_id] = {"attempts": attempts, "not_before": not_before, "since": since,
                                        "ambiguous": ambiguous}  # fmt: skip
            self._record_alert(outbox_id, entry["world_id"], alert)
            _release(self._send_leases, outbox_id, holder)

    def _release_lease(self, kind: str, outbox_id: str, holder: str) -> None:  # kind: "send"/"transfer"
        with self._lock:
            _release(self._send_leases if kind == "send" else self._transfer_leases, outbox_id, holder)

    def _claim_oldest_pending_transfer(
        self,
        holder: str,
        now: str,
        lease_seconds: float,
        exclude: frozenset[str] = frozenset(),
        only: str | None = None,
    ) -> tuple[str, str, dict] | None:  # oldest pending transfer of a world not in `exclude` (and == `only`, if set)
        with self._lock:
            seen_worlds = set(exclude)
            for outbox_id, (world_id, transfer) in self._pending_transfers.items():
                if world_id in seen_worlds or only not in (None, world_id):
                    continue
                seen_worlds.add(world_id)
                if _try_claim(self._transfer_leases, outbox_id, holder, now, lease_seconds):
                    return (outbox_id, world_id, deepcopy(transfer))  # a mutating emit never corrupts a retry
            return None

    def _pending_alerts_of(self, only: str | None) -> list[tuple[str, dict]]:  # at-least-once; alert_id dedupes
        with self._lock:
            items = self._pending_alerts.items()
            return [(oid, deepcopy(part)) for oid, (world, part) in items if only in (None, world)]

    def _discard_pending_alert(self, outbox_id: str) -> None:
        with self._lock:
            self._pending_alerts.pop(outbox_id, None)

    def _discard_pending_transfer(self, outbox_id: str, holder: str) -> None:  # always removed once delivered
        with self._lock:
            self._pending_transfers.pop(outbox_id, None)
            _release(self._transfer_leases, outbox_id, holder)
