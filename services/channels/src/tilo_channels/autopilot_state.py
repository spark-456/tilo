"""tilo_channels.autopilot_state: a card's outbox entry and its stop, for Email Autopilot (FR-CHN-11; PRD 11.4 Undo,
11.6 "no send after cancel"; OB-02, OB-03).

The card store holds create-if-absent slots next to each card: `#decision` (an L1 card's one Send, close or edit),
`#stop` (any Cancel or Edit of an L2 card: from then on no entry of the card may send), `#enqueued` (an entry was
stored) and `#cancelled` (the outbox cancelled it). Each slot keeps its first writer. No path enqueues once `#stop`
is recorded; an enqueue that raced a stop reads `#stop` again afterwards and cancels its own entry. A stop answers
"cancelled" only when the outbox cancelled the entry or no entry was ever stored, "too_late" only once the earliest
send time has passed, and otherwise raises CancelPending, so the owner can retry: a failed cancel is never reported
as done. Outbox port: `enqueue(entry, evidence)` (a repeated idempotency key returns the stored entry), `cancel(id)`.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

ACTION_TYPE = "send_email"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class CancelPending(RuntimeError):
    """The outbox did not confirm the cancel of an entry that may still be scheduled: retry."""


class Outbox(Protocol):  # the names of tilo_connectors.outbox.Outbox, which tilo-channels never imports (BQ-158)
    def enqueue(self, entry: dict, evidence: dict) -> dict: ...
    def cancel(self, outbox_id: str) -> dict: ...


class CardStore(Protocol):  # JSON-able documents keyed (user_id, key): get, atomic create-if-absent, put
    def get(self, user_id: str, key: str) -> dict | None: ...
    def create(self, user_id: str, key: str, value: dict) -> bool: ...
    def put(self, user_id: str, key: str, value: dict) -> None: ...


def timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


def ulid(ms: int) -> str:
    value = (ms << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


class Ledger:
    def __init__(
        self,
        *,
        cards: CardStore,
        outbox: Outbox,
        clock: Callable[[], float],
        world_id: str,
        run_id: str,
        connector: str,
    ) -> None:
        self._cards, self._outbox, self._clock = cards, outbox, clock
        self._world_id, self._run_id, self._connector = world_id, run_id, connector

    def first(self, user_id: str, card_id: str, slot: str, by: str) -> str:
        """Claims `slot` for `by` unless it is taken; returns whoever holds it."""
        key = f"{card_id}#{slot}"
        if self._cards.create(user_id, key, {"by": by}):
            return by
        return str((self._cards.get(user_id, key) or {}).get("by"))

    def holds(self, user_id: str, card_id: str, slot: str) -> bool:
        return self._cards.get(user_id, f"{card_id}#{slot}") is not None

    def schedule(self, user_id: str, doc: dict[str, Any]) -> dict | None:
        """The L2 card's one entry, enqueued (or found) under its key; None once the card is stopped."""
        card_id = doc["card_id"]
        if self.holds(user_id, card_id, "stop"):
            self._try_cancel(user_id, doc)  # completes a stop whose cancel the outbox refused earlier
            return None
        entry = self.enqueue(doc)
        self._cards.create(user_id, f"{card_id}#enqueued", {})
        if self.holds(user_id, card_id, "stop"):  # a stop raced this enqueue: cancel what was just stored
            self._try_cancel(user_id, doc)
            return None
        return entry

    def stop(self, user_id: str, doc: dict[str, Any], by: str) -> str:
        """Stops the L2 card's send, whichever Cancel or Edit holds `#stop`: "cancelled" or "too_late"."""
        card_id = doc["card_id"]
        self.first(user_id, card_id, "stop", by)
        if self._try_cancel(user_id, doc) or self.holds(user_id, card_id, "cancelled"):
            return "cancelled"
        if not self.holds(user_id, card_id, "enqueued"):  # never stored, and no enqueue may start now
            return "cancelled"
        if round(self._clock() * 1000) < doc["scheduled_ms"]:  # it cannot have been sent yet
            raise CancelPending("the outbox did not confirm the cancel")
        return "too_late"

    def _try_cancel(self, user_id: str, doc: dict[str, Any]) -> bool:
        try:
            self._outbox.cancel(doc["outbox_id"])
        except Exception:  # not scheduled, unknown, or the outbox is unavailable: the caller decides
            return False
        self._cards.create(user_id, f"{doc['card_id']}#cancelled", {})
        return True

    def enqueue(self, doc: dict[str, Any]) -> dict:
        """The card's entry under its idempotency key: a replay returns the stored entry and never adds one."""
        ms = round(self._clock() * 1000)
        created, window, policy = timestamp(ms), doc["undo_window_s"], doc["level"] == "L2"
        authority = {"by": "policy", "ref": doc["policy_id"]} if policy else {"by": "person", "ref": doc["user_id"]}
        entry = {
            "id": doc["outbox_id"] or ulid(ms),
            "idempotency_key": f"autopilot:{doc['card_id']}",
            "world_id": self._world_id,
            "run_id": self._run_id,
            "action_type": ACTION_TYPE,
            "connector": self._connector,
            "recipients": list(dict.fromkeys(doc["to"] + doc["cc"])),
            "attachments": [],
            "item": doc["item"],
            "destination": doc["thread_id"],
            "modifiers": doc["modifiers"],
            "risk_tier": doc["tier"],
            "authz": authority | {"at": created},
            "undo_window_s": window,
            "scheduled_at": timestamp(ms + window * 1000),
            "state": "scheduled" if window else "queued",
            "created_at": created,
        }
        return self._outbox.enqueue(entry, {"instruction_id": doc["instruction_id"], "level": doc["level"]})
