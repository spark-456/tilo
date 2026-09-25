"""tilo_connectors.outbox — the only path to a side effect (SEC-03, PRD 12.1). enqueue() writes
only a new entry (OB-02, OB-05), authorised by tilo_policy.check_entry (OB-01/OB-05); a retry on
the same world_id + idempotency_key is a no-op (OB-03). dispatch_due() sends every entry due,
minting a single-use Grant no caller outside this module can construct (SEC-03). Several
instances share one store (tests/API.md "Several instances, restarts", "One transfer per
entry"): claiming an entry is a leased compare-and-set, a fresh clock reading per claim, so an
in-flight send is never claimed twice and a later lease in a slow batch is never already
expired; an adapter Exception is ambiguous (the send may have happened) so the entry gives up
its lease and stays "sending", still due, the batch going on — only a missing adapter is a final
"failed". Marking sent and recording the pending data.transfer are one store write (PI-17: never
a sent entry with no transfer). Only the ordered flush emits, claiming the oldest pending
transfer under its own lease, so one instance emits a given transfer and a later one waits on an
earlier one; an emit error there never stops the batch. Public surface: tests/API.md.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import tilo_policy

from ._schema import outbox_validator
from ._time import add_seconds
from .errors import MissingGrant, OutboxRefused
from .store import InMemoryOutboxStore

# "queued" and "sending" (a process death, a released lease, or an adapter Exception — all
# ambiguous, so it stays retryable; the adapter's own key dedupe keeps it at one send) are
# always worth attempting; "scheduled" waits out its undo window; "sent", "cancelled" and
# "failed" (only a missing adapter, a definite non-send) are terminal.
_ALWAYS_DUE_STATES = ("queued", "sending")
_LEASE_SECONDS = 30  # generous next to any real adapter call; a dead holder's lease still expires

# Ids of Grant objects currently authorised for the one send Outbox.dispatch_due() minted them
# for (SEC-03). Private to this module; a Grant built any other way is never a member.
_LIVE_GRANTS: set[int] = set()


def _transfer_event(entry: dict) -> dict:
    """The one data.transfer a sent entry emits (PI-16/17): direction "out", this entry's id,
    authz and pinned item, unchanged."""
    return {
        "type": "data.transfer",
        "authz": entry["authz"],
        "data": {
            "connector": entry["connector"],
            "action_type": entry["action_type"],
            "direction": "out",
            "artifact": entry["item"],
            "outbox_id": entry["id"],
            "risk_tier": entry["risk_tier"],
        },
    }


@dataclass(frozen=True)
class Grant:
    """SEC-03: the capability a side-effect method requires, minted only by
    Outbox.dispatch_due() and live only for the one send it names. A Grant built any other way
    (its own constructor, object.__new__, a subclass) verifies as invalid: validity is tracked
    by object identity in this module's own registry, not by field values."""

    outbox_id: str
    world_id: str
    idempotency_key: str

    def verify(self, idempotency_key: str) -> None:
        """Raises unless this exact object is currently live AND names the send it is being
        used for — a live grant minted for one key never covers a call made with another."""
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
        self._store = store
        self._connectors = connectors
        self._emit = emit
        self._clock = clock

    # -- enqueue -----------------------------------------------------------------------------

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        errors = sorted(outbox_validator().iter_errors(entry), key=lambda e: list(e.path))
        if errors:
            raise OutboxRefused(f"OB-05: entry fails outbox.schema.json: {errors[0].message}")

        self._check_fresh_state(entry)

        existing = self._store.get_by_idempotency_key(entry["world_id"], entry["idempotency_key"])
        if existing is not None:
            return existing
        if self._store.get(entry["id"]) is not None:
            raise OutboxRefused(f"id {entry['id']!r} is already stored under a different idempotency_key")

        # Taken before check_entry and stored as-is: the caller changing its own dict afterwards
        # changes nothing here.
        snapshot = deepcopy(entry)
        case = {**deepcopy(evidence), "entry": deepcopy(snapshot), "transfer": None, "rule": None}
        verdict = tilo_policy.check_entry(case)
        if verdict is not None:
            raise OutboxRefused(f"{verdict}: entry is not authorised")

        if not self._store._insert_if_absent(snapshot):
            # Lost a race with a concurrent enqueue of the same id or the same (world_id, key):
            # the store never overwrites.
            existing = self._store.get_by_idempotency_key(entry["world_id"], entry["idempotency_key"])
            if existing is not None:
                return existing
            raise OutboxRefused(f"id {entry['id']!r} is already stored under a different idempotency_key")
        return deepcopy(snapshot)

    def _check_fresh_state(self, entry: dict) -> None:
        """OB-02: enqueue only ever introduces a brand-new entry — "queued" with no undo window,
        else "scheduled" with scheduled_at == created_at + undo_window_s. Any other state (a
        later stage of the entry's life) is refused outright, as is a schedule so far out that
        computing it overflows."""
        undo_window_s = entry["undo_window_s"]
        expected_state = "queued" if undo_window_s == 0 else "scheduled"
        if entry["state"] != expected_state:
            raise OutboxRefused(f"OB-02: a new entry must be {expected_state!r}, got {entry['state']!r}")
        try:
            expected_scheduled_at = add_seconds(entry["created_at"], undo_window_s)
        except (ValueError, TypeError, OverflowError) as exc:
            raise OutboxRefused(f"OB-02: cannot compute scheduled_at: {exc}") from exc
        if entry["scheduled_at"] != expected_scheduled_at:
            raise OutboxRefused(
                f"OB-02: scheduled_at must equal created_at + undo_window_s (expected {expected_scheduled_at!r})"
            )

    # -- cancel --------------------------------------------------------------------------------

    def cancel(self, outbox_id: str) -> dict:
        updated = self._store._compare_and_set_state(outbox_id, ("scheduled",), "cancelled")
        if updated is None:
            raise OutboxRefused(f"cannot cancel {outbox_id!r}: only a 'scheduled' entry can be cancelled")
        return updated

    # -- dispatch ------------------------------------------------------------------------------

    def dispatch_due(self) -> list[dict]:
        now = self._clock()
        due = [entry for entry in self._store.all_entries() if self._is_due(entry, now)]
        settled = [self._dispatch_one(entry["id"]) for entry in due]
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
        claimed = self._store._claim_for_sending(outbox_id, holder, self._clock(), _LEASE_SECONDS)
        if claimed is None:
            return None  # leased to someone else, or not claimable right now

        adapter = self._connectors.get(claimed["connector"])
        if adapter is None:
            return self._store._finalize_claim(outbox_id, holder, "failed")

        grant = Grant(outbox_id=claimed["id"], world_id=claimed["world_id"], idempotency_key=claimed["idempotency_key"])
        _LIVE_GRANTS.add(id(grant))
        try:
            adapter.send_reply(
                claimed["destination"], claimed["item"], claimed["recipients"], claimed["idempotency_key"], grant
            )
        except Exception:
            self._store._release_claim(outbox_id, holder)
            return None
        except BaseException:
            # A process death (or a KeyboardInterrupt standing in for one): still ambiguous, so
            # give up the lease too — the caller is about to lose this process either way, and
            # an immediate retry (by this or another instance) should not have to wait it out.
            self._store._release_claim(outbox_id, holder)
            raise
        finally:
            _LIVE_GRANTS.discard(id(grant))

        # One atomic write: the entry moves to "sent" and its data.transfer becomes pending in
        # the same store operation (PI-17) — nothing here emits it; the flush below does.
        return self._store._finalize_claim(outbox_id, holder, "sent", _transfer_event(claimed))

    def _flush_pending_transfers(self) -> None:
        """The single emit path (PI-17): claims the oldest pending data.transfer under a fresh
        lease, emits it, and discards it — one instance at a time, oldest first. Stops as soon
        as a claim or an emit does not succeed, so a later transfer never jumps ahead of one
        still outstanding."""
        while True:
            holder = uuid.uuid4().hex
            claim = self._store._claim_oldest_pending_transfer(holder, self._clock(), _LEASE_SECONDS)
            if claim is None:
                return
            outbox_id, transfer = claim
            try:
                self._emit(transfer)
            except Exception:
                self._store._release_pending_transfer_claim(outbox_id, holder)
                return
            self._store._discard_pending_transfer(outbox_id, holder)
