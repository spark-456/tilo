"""tilo_connectors.outbox — the only path to a side effect (SEC-03, PRD 12.1). Outbox.enqueue
writes only a new entry: schema-valid (OB-05), "queued" or "scheduled" to match undo_window_s
(OB-02), never overwriting a stored id, and authorised by tilo_policy.check_entry (OB-01/OB-05);
a retry with the same world_id + idempotency_key is a no-op (OB-03). Outbox.dispatch_due() sends
every entry currently due, minting a single-use Grant no caller outside this module can
construct, so a connector adapter's side-effect method can only run from here (SEC-03). An
adapter Exception is ambiguous (the side effect may have happened) so the entry just stays
"sending" — still due, retried by the next dispatch_due(), the batch going on regardless — and
only a missing adapter for the connector is a final "failed" (tests/API.md "Failures"). Public
surface: tests/API.md.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import tilo_policy

from ._schema import outbox_validator
from ._time import add_seconds
from .errors import MissingGrant, OutboxRefused
from .store import InMemoryOutboxStore

# States dispatch_due() treats as due: "queued" and "sending" (left there by a process death or
# an adapter Exception — either way ambiguous, so it stays retryable; the adapter's own key
# dedupe keeps it at one send) are always due; "scheduled" waits out its undo window; "sent",
# "cancelled" and "failed" (only a missing adapter, a definite non-send) are terminal.
_ALWAYS_DUE_STATES = ("queued", "sending")
_CLAIMABLE_STATES = ("queued", "scheduled", "sending")

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

    def verify(self) -> None:
        if id(self) not in _LIVE_GRANTS:
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
        # Transfers a send emitted but were not yet handed to `emit` successfully (PI-14: no
        # field but state changes on the entry itself, so this bookkeeping lives here instead).
        self._pending_transfers: dict[str, dict] = {}

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

        case = {**deepcopy(evidence), "entry": deepcopy(entry), "transfer": None, "rule": None}
        verdict = tilo_policy.check_entry(case)
        if verdict is not None:
            raise OutboxRefused(f"{verdict}: entry is not authorised")

        if not self._store._insert_if_absent(entry):
            # Lost a race with a concurrent enqueue of the same id: the store never overwrites.
            existing = self._store.get_by_idempotency_key(entry["world_id"], entry["idempotency_key"])
            if existing is not None:
                return existing
            raise OutboxRefused(f"id {entry['id']!r} is already stored under a different idempotency_key")
        return deepcopy(entry)

    def _check_fresh_state(self, entry: dict) -> None:
        """OB-02: enqueue only ever introduces a brand-new entry — "queued" with no undo window,
        else "scheduled" with scheduled_at == created_at + undo_window_s. Any other state (a
        later stage of the entry's life) is refused outright."""
        undo_window_s = entry["undo_window_s"]
        expected_state = "queued" if undo_window_s == 0 else "scheduled"
        if entry["state"] != expected_state:
            raise OutboxRefused(f"OB-02: a new entry must be {expected_state!r}, got {entry['state']!r}")
        try:
            expected_scheduled_at = add_seconds(entry["created_at"], undo_window_s)
        except (ValueError, TypeError) as exc:
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
        claimed = self._store._compare_and_set_state(outbox_id, _CLAIMABLE_STATES, "sending")
        if claimed is None:
            return None  # already claimed elsewhere (a racing dispatch, or a cancel just won)

        adapter = self._connectors.get(claimed["connector"])
        if adapter is None:
            return self._store._compare_and_set_state(outbox_id, ("sending",), "failed")

        grant = Grant(outbox_id=claimed["id"], world_id=claimed["world_id"], idempotency_key=claimed["idempotency_key"])
        _LIVE_GRANTS.add(id(grant))
        try:
            adapter.send_reply(
                claimed["destination"], claimed["item"], claimed["recipients"], claimed["idempotency_key"], grant
            )
        except Exception:
            # Ambiguous: the side effect may already have happened. Marking it failed here could
            # hide a real send with no event for it (PRD 9.4), so the entry just stays "sending"
            # — still due — and the next dispatch_due() retries it; the adapter's own
            # (world_id, idempotency_key) dedupe keeps it to one send. The batch goes on.
            return None
        finally:
            _LIVE_GRANTS.discard(id(grant))

        sent = self._store._compare_and_set_state(outbox_id, ("sending",), "sent")
        if sent is None:
            return None  # this Outbox instance's own claim was somehow undone; nothing to emit
        self._pending_transfers[outbox_id] = _transfer_event(sent)
        self._emit(self._pending_transfers[outbox_id])  # may raise; retried by _flush_pending_transfers
        del self._pending_transfers[outbox_id]
        return sent

    def _flush_pending_transfers(self) -> None:
        """A sent entry's data.transfer that `emit` previously raised on (PI-17): exactly one is
        ever emitted per entry, so a later dispatch_due() keeps retrying only the ones still
        outstanding."""
        for outbox_id in list(self._pending_transfers):
            self._emit(self._pending_transfers[outbox_id])
            del self._pending_transfers[outbox_id]
