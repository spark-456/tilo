"""tilo_channels.autopilot_state: a card's outbox entry and its stop, for Email Autopilot (FR-CHN-11; PRD 11.4 Undo,
11.6 "L2 send can be cancelled within 60 s; no send after cancel"; OB-02, OB-03).

Slots are create-if-absent documents next to each card; each keeps its first writer. `#decision` holds an L1 card's
one Send, close or edit. An L2 card's entry and its stop follow this protocol (each side writes its own slot, then
reads the other's, so at least one side sees the other):

  ENQUEUE side, `schedule` (preview, replay, Send):
    E1 write `#enqueuing`. E2 read `#stop`: if set, enqueue nothing (when `#enqueuing` was already there, settle the
    stop as S3, which may raise). E3 enqueue under the key `autopilot:<card_id>` with the recorded entry id (a repeated
    key returns the stored entry; a revoked key is refused). E4 read `#stop` again (also after E3 failed): if set,
    settle the stop (S3); an unconfirmed cancel raises CancelPending, so the caller retries; it is never swallowed.
  STOP side, `stop` (Cancel, Edit), never calling `enqueue` (CHN-GATE-A, BQ-186):
    S0 queue the stop in `StopQueue` (BQ-187). S1 write `#stop` (from now on no entry of the card may send). S2 if
    `#enqueuing` is not there, no enqueue ever started and every later one stops at E2: write `#cancelled`. S3 (settle,
    also the sweeper's): revoke the key (cancels a stored scheduled entry, or makes the outbox refuse to create it),
    else cancel the recorded id, else read the entry by key. "cancelled" (and `#cancelled`) only when the outbox
    revoked the absent key, confirmed the cancel or showed the entry cancelled; "too_late" (and `#too_late`) only when
    it showed the entry sending, sent or failed; anything unconfirmed raises CancelPending and stays queued. Elapsed
    time is never evidence. A settled stop leaves the queue.

`#cancelled` therefore means no entry of the card can ever send. A crash anywhere leaves either no recorded stop (the
caller saw an error and retries) or a queued one that a retry, E2, E4 or the sweeper completes.
"""

from __future__ import annotations

import copy
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

from tilo_policy.schemas import conforms

ACTION_TYPE = "send_email"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
DECISION_MAX_AGE_S = 30  # a stored decision authorises an entry at most this long after its `authz.at` (BQ-245, BQ-249)
SKEW_S = 5  # a decision stamped this far ahead of our clock is still read as now


class CancelPending(RuntimeError):
    """The outbox did not confirm the cancel of an entry that may still be scheduled: retry."""


class StaleDecision(RuntimeError):
    """The L2 entry would be created outside its decision's freshness bound: nothing is enqueued, decide again."""


class Outbox(Protocol):  # the names of tilo_connectors.outbox.Outbox, which tilo-channels never imports (BQ-158)
    def enqueue(self, entry: dict, evidence: dict) -> dict: ...
    def cancel(self, outbox_id: str) -> dict: ...
    def get(self, outbox_id: str) -> dict | None: ...  # read port: a copy or None; never writes
    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None: ...
    def revoke(self, world_id: str, idempotency_key: str) -> dict | None: ...  # never creates an entry (BQ-186)


class StopQueue(Protocol):  # stops not yet confirmed, shared by every instance (Firestore in production; BQ-187)
    def add(self, user_id: str, card_id: str) -> None: ...
    def pending(self) -> list[tuple[str, str]]: ...
    def remove(self, user_id: str, card_id: str) -> None: ...


class CardStore(Protocol):  # JSON-able documents keyed (user_id, key): get, atomic create-if-absent, put
    def get(self, user_id: str, key: str) -> dict | None: ...
    def create(self, user_id: str, key: str, value: dict) -> bool: ...
    def put(self, user_id: str, key: str, value: dict) -> None: ...


def timestamp(ms: int) -> str:
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


def parse_ms(stamp: Any) -> int | None:
    """Epoch milliseconds of a contract timestamp (RFC 3339 UTC, three fractional digits); None for anything else."""
    if type(stamp) is not str or not conforms("common.schema.json#/$defs/timestamp", stamp):
        return None
    try:
        return round(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC).timestamp() * 1000)
    except (ValueError, OverflowError, OSError):  # the pattern allows dates that do not exist
        return None


def fresh(authz_at: Any, now_ms: int) -> bool:
    """`authz_at` is no more than the skew ahead of `now_ms` and no more than the bound behind it."""
    at = parse_ms(authz_at)
    return at is not None and -SKEW_S * 1000 <= now_ms - at <= DECISION_MAX_AGE_S * 1000


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
        stops: StopQueue | None = None,
    ) -> None:
        self._cards, self._outbox, self._clock, self._stops = cards, outbox, clock, stops
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
                self.settle(user_id, doc)
            return None
        entry = None
        try:
            entry = self.enqueue(doc)  # E3
        except Exception:
            if not self.holds(user_id, card_id, "stop"):
                raise  # a stop that revoked the key makes the outbox refuse it; E4 answers that
        if self.holds(user_id, card_id, "stop"):  # E4: a stop raced this enqueue
            self.settle(user_id, doc)
            return None
        return entry

    def stop(self, user_id: str, doc: dict[str, Any], by: str) -> str:
        """Stops the L2 card's send, whichever Cancel or Edit holds `#stop` (S0 to S3): "cancelled" or "too_late"."""
        card_id = doc["card_id"]
        if self._stops is not None:
            self._stops.add(user_id, card_id)  # S0: queued before it is recorded, so no crash hides it from a sweep
        self.first(user_id, card_id, "stop", by)  # S1, before the outbox is first called
        if not self.holds(user_id, card_id, "enqueuing"):  # S2
            self._cards.create(user_id, f"{card_id}#cancelled", {})
        return self.settle(user_id, doc)  # S3

    def settled(self, user_id: str, card_id: str) -> str | None:
        return next((s for s in ("cancelled", "too_late") if self.holds(user_id, card_id, s)), None)

    def ours(self, doc: dict[str, Any]) -> bool:
        """The card was decided in this ledger's world, so its entry (if any) is under this world's key."""
        return doc.get("world_id") == self._world_id

    def settle(self, user_id: str, doc: dict[str, Any]) -> str:
        """S3 for a recorded stop: "cancelled" or "too_late", recorded and dequeued; raises CancelPending."""
        card_id = doc["card_id"]
        status = self.settled(user_id, card_id)
        if status is None:
            if not self.ours(doc):  # another world's key proves nothing about this card's entry
                raise CancelPending("the card's entry is another world's: only that world can confirm the stop")
            status = self._confirm(doc)
            self._cards.create(user_id, f"{card_id}#{status}", {})  # the outbox's answer, so any writer agrees
        if self._stops is not None:
            self._stops.remove(user_id, card_id)
        return status

    def _confirm(self, doc: dict[str, Any]) -> str:
        """The outbox's word on the card's entry; never enqueues. None from `revoke` means the absent key is revoked;
        None from a read proves nothing (an enqueue may be in flight)."""
        key, world = f"autopilot:{doc['card_id']}", doc["world_id"]  # the card's own world (checked by settle)
        asks: list[Callable[[], dict | None]] = [
            lambda: self._outbox.revoke(world, key) or {"state": "cancelled"},
            lambda: self._outbox.cancel(doc["outbox_id"]),
            lambda: self._outbox.get_by_idempotency_key(world, key),
        ]
        for ask in asks:
            try:
                state = (ask() or {}).get("state", "scheduled")
            except Exception:  # unavailable, refused, or the answer was lost: ask the next way
                continue
            if state != "scheduled":
                return "cancelled" if state == "cancelled" else "too_late"  # sending, sent or failed: it went
        raise CancelPending("the outbox did not confirm the stop")

    def stored(self, doc: dict[str, Any]) -> dict | None:
        """The card's entry if the outbox holds one under its key (read only)."""
        return self._outbox.get_by_idempotency_key(doc["world_id"], f"autopilot:{doc['card_id']}")

    def entry_for(self, doc: dict[str, Any], authz: dict[str, Any] | None = None) -> dict:
        """The card's entry. Only in the card's own world: an entry elsewhere is one no stop of this card would find.
        A person's `authz` (the approval's, OB-01) is copied as given, never re-stamped; so is the authz of an L2
        card's stored `policy.applied` (CHN-WIRE-4), whose time is the decision's, not now."""
        if not self.ours(doc):
            raise PermissionError("the card belongs to another world: its entry is never created here")
        ms = round(self._clock() * 1000)
        created, window, policy = timestamp(ms), doc["undo_window_s"], doc["level"] == "L2"
        authority = {"by": "policy", "ref": doc["policy_id"]} if policy else {"by": "person", "ref": doc["user_id"]}
        if authz is None and policy and isinstance(doc.get("policy_applied"), dict):
            authz = doc["policy_applied"]["authz"]
            if not fresh(authz.get("at"), ms):  # judged on the clock read that stamps created_at (BQ-245)
                raise StaleDecision("the card's decision is outside its freshness bound")
        return {
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
            "authz": copy.deepcopy(authz) if authz is not None else authority | {"at": created},
            "undo_window_s": window,
            "scheduled_at": timestamp(ms + window * 1000),
            "state": "scheduled" if window else "queued",
            "created_at": created,
        }

    def enqueue(self, doc: dict[str, Any], entry: dict | None = None, evidence: dict | None = None) -> dict:
        """The card's entry under its idempotency key: a replay returns the stored entry and never adds one."""
        if entry is None:
            try:
                stored = self.stored(doc)
            except Exception:  # a failed read proves nothing: build the entry as before (stale still fails closed)
                stored = None
            if stored is not None:
                return stored  # the key is taken: that entry stands at any age, no fresh decision is needed (#343)
        entry = entry or self.entry_for(doc)
        return self._outbox.enqueue(entry, evidence or {"instruction_id": doc["instruction_id"], "level": doc["level"]})


def enqueue_digest(
    outbox: Outbox,
    entry: dict[str, Any],
    *,
    policy_applied: dict[str, Any],
    policy: Mapping[str, Any] | None,
    world_owner: str,
    emit: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Enqueues a policy-authorised L3 daily digest entry once its full OB-01 evidence opens the gate (FR-CHN-18)."""
    from tilo_channels import autopilot_gate

    if not isinstance(policy, Mapping):
        return None
    evidence: dict[str, Any] = {"reserved_by": None, "authorised_by": copy.deepcopy(policy_applied)}
    evidence |= {"policy": copy.deepcopy(dict(policy)), "team_lead": None, "world_owner": world_owner}
    evidence |= {"instruction": None, "earlier_applied": []}
    if not autopilot_gate.opens(entry, evidence):
        return None
    if emit is not None:
        emit(copy.deepcopy(policy_applied))
    return outbox.enqueue(entry, evidence)
