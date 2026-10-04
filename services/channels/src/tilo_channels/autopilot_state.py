"""tilo_channels.autopilot_state: a card's outbox entry and its stop, for Email Autopilot (FR-CHN-11; PRD 11.4 Undo,
11.6 "L2 send can be cancelled within 60 s; no send after cancel"; OB-02, OB-03).

Slots are create-if-absent documents next to each card; each keeps its first writer. `#decision` holds an L1 card's
one Send, close or edit. An L2 card's entry and its stop follow this protocol (each side writes its own slot, then
reads the other's, so at least one side sees the other):

  ENQUEUE side, `schedule` (preview, replay, Send):
    E1 write `#enqueuing`. E2 read `#stop`: if set, enqueue nothing (when `#enqueuing` was already there, settle the
    stop as S3, which may raise). E3 enqueue under the key `autopilot:<card_id>` with the recorded entry id (a repeated
    key returns the stored entry). E4 read `#stop` again: if set, settle the stop (S3); an unconfirmed cancel raises
    CancelPending, so the caller retries; it is never swallowed.
  STOP side, `stop` (Cancel, Edit):
    S1 write `#stop` (any Cancel or Edit; from now on no entry of the card may send). S2 if `#cancelled` is there:
    "cancelled". If `#enqueuing` is not there, no enqueue ever started and every later one stops at E2: write
    `#cancelled`, "cancelled". S3 (settle) otherwise: cancel the recorded id; if the outbox refuses, look the entry up
    by enqueueing the same key again (it returns the stored entry, or stores it now to be cancelled next) and cancel
    it if it is scheduled. "cancelled" (and `#cancelled`) only when the outbox confirmed the cancel or showed the entry
    cancelled; "too_late" only when it showed the entry sending, sent or failed; anything unconfirmed raises
    CancelPending. Elapsed time is never evidence.

`#cancelled` therefore means no entry of the card can ever send. A crash anywhere leaves either a stop that is not yet
answered (the caller retries, and E2 or S3 completes it) or a confirmed one.
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
        """The L2 card's one entry, enqueued (or found) under its key (E1 to E4); None once the card is stopped."""
        card_id = doc["card_id"]
        claimed = self.holds(user_id, card_id, "enqueuing")  # E1, written once: a replay finds it already there
        fresh = not claimed and self._cards.create(user_id, f"{card_id}#enqueuing", {})
        if self.holds(user_id, card_id, "stop"):  # E2
            if not fresh:  # an earlier enqueue may have stored the entry: complete the recorded stop
                self._settle(user_id, doc)
            return None
        entry = self.enqueue(doc)  # E3
        if self.holds(user_id, card_id, "stop"):  # E4: a stop raced this enqueue
            self._settle(user_id, doc)
            return None
        return entry

    def stop(self, user_id: str, doc: dict[str, Any], by: str) -> str:
        """Stops the L2 card's send, whichever Cancel or Edit holds `#stop` (S1 to S3): "cancelled" or "too_late"."""
        card_id = doc["card_id"]
        self.first(user_id, card_id, "stop", by)  # S1
        if self.holds(user_id, card_id, "cancelled"):  # S2
            return "cancelled"
        if not self.holds(user_id, card_id, "enqueuing"):
            self._cards.create(user_id, f"{card_id}#cancelled", {})
            return "cancelled"
        return self._settle(user_id, doc)  # S3

    def _settle(self, user_id: str, doc: dict[str, Any]) -> str:
        card_id = doc["card_id"]
        if self.holds(user_id, card_id, "cancelled"):
            return "cancelled"
        try:
            self._outbox.cancel(doc["outbox_id"])
        except Exception:  # not stored, not scheduled, or the outbox is unavailable: look the entry up
            try:
                entry = self.enqueue(doc)  # the stored entry under the card's key, or one stored now to be cancelled
            except Exception as exc:
                raise CancelPending("the outbox could not be read") from exc
            if entry["state"] not in ("scheduled", "cancelled"):
                return "too_late"  # sending, sent or failed: the outbox says it went
            if entry["state"] == "scheduled":
                try:
                    self._outbox.cancel(entry["id"])
                except Exception as exc:
                    raise CancelPending("the outbox did not confirm the cancel") from exc
        self._cards.create(user_id, f"{card_id}#cancelled", {})
        return "cancelled"

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
