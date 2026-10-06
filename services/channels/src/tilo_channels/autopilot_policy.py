"""tilo_channels.autopilot_policy: the Autopilot's L2 decision, asked of the policy port (CHN-WIRE-4, FR-CHN-11;
PRD 10.4; OB-01, OB-02, OB-05; BQ-242 to BQ-248). Fail closed: anything but a clean `run_after_undo` for exactly this
card is L1.

`decide(user_id, proposal)` is asked once, when the card is decided; its `policy.applied` part is stored in the card by
the atomic create (slot 0). A usable decision is only used for the card's FIRST enqueue, and only while it is at most
`DECISION_MAX_AGE_S` old and the card still says what it was made for (recipients, destination, item, T2, no modifier).
Otherwise, before any entry exists, the engine is asked again with the stored proposal: a clean answer is slot n + 1
(create-if-absent, so racing instances agree on one), anything else (or a raise) is a `drop` slot: the card is L1
(same id and reserved outbox id), its `approval.requested` is emitted once by whoever created the slot. Slots are
never rewritten. Once the card's entry exists nothing is asked again. A policy object without `decide` keeps the
old `level()` hint path (no part, no slots).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import tilo_policy
from tilo_policy.schemas import conforms, event_ok

from tilo_channels.autopilot_gate import gate_id_for, requested_part
from tilo_channels.autopilot_state import (
    ACTION_TYPE,
    DECISION_MAX_AGE_S,
    SKEW_S,
    CardStore,
    Ledger,
    fresh,
    parse_ms,
)

__all__ = ["DECISION_MAX_AGE_S", "PolicyPort"]

MAX_WINDOW_S = 3600  # policy.schema.json caps undo_window_s here
MAX_REDECISIONS = 3  # replays after the bound that the outbox keeps refusing must not add decisions for ever
_ROUNDS = 4
_POLICY_ID = "common.schema.json#/$defs/policy_id"


def _is(value: Any, expected: str) -> bool:
    return type(value) is str and value == expected  # exact str: a subclass cannot vouch for itself


def _usable(d: Any, now_ms: int) -> dict[str, str] | None:
    """The authz of a clean decision for this card (BQ-248), built from validated fields: run_after_undo, T2, L2, no
    modifier, a policy stamp naming a valid policy id, a readable `at` not ahead of us, and an int window of 1 s or
    more; None otherwise."""
    if type(d) is not tilo_policy.Decision:
        return None
    if not (_is(d.outcome, "run_after_undo") and _is(d.tier, "T2") and _is(d.level, "L2")):
        return None
    authz, window = d.authz, d.undo_window_s
    if type(d.modifiers) is not tuple or d.modifiers or type(authz) is not dict or len(authz) != 3:
        return None
    by, ref, stamp = authz.get("by"), authz.get("ref"), authz.get("at")
    at = parse_ms(stamp)
    if (
        not _is(by, "policy")
        or type(ref) is not str
        or type(d.policy_id) is not str
        or ref != d.policy_id
        or at is None
        or not conforms(_POLICY_ID, ref)
    ):
        return None
    if at > now_ms + SKEW_S * 1000 or type(window) is not int or not 1 <= window <= MAX_WINDOW_S:
        return None
    return {"by": "policy", "ref": ref, "at": str(stamp)}


def _proposal(stored: dict) -> tilo_policy.Proposal:
    recipients = tuple(stored["recipients"])
    facts = tilo_policy.SideEffectFacts(recipients=recipients, known_recipients=recipients)
    keys = ("world_id", "action_type", "connector", "district", "destination", "item", "credits")
    return tilo_policy.Proposal(**{k: copy.deepcopy(stored[k]) for k in keys}, facts=facts, instruction=None)


def _bound(doc: dict, stored: dict, connector: str) -> bool:
    """BQ-247: the card still says what the decision was made for."""
    return (
        doc["tier"] == "T2"
        and not doc["modifiers"]
        and bool(stored["recipients"])
        and tuple(dict.fromkeys(doc["to"] + doc["cc"])) == tuple(stored["recipients"])
        and doc["thread_id"] == stored["destination"]
        and doc["item"] == stored["item"]
        and stored["connector"] == connector
    )


class PolicyPort:
    def __init__(
        self,
        *,
        policy: Any,
        cards: CardStore,
        ledger: Ledger,
        clock: Callable[[], float],
        emit: Callable[[dict], None],
        world_id: str,
        connector: str,
        district: str,
    ) -> None:
        self._policy, self._cards, self._ledger, self._clock, self._emit = policy, cards, ledger, clock, emit
        self._ids = {"world_id": world_id, "action_type": ACTION_TYPE, "connector": connector, "district": district}

    def decides(self) -> bool:
        return callable(getattr(self._policy, "decide", None))

    def first(self, user_id: str, doc: dict[str, Any], now_ms: int) -> dict[str, Any] | None:
        """The part of a new card's decision (doc["proposal"] is stored with it), or None: the card is L1."""
        recipients = list(dict.fromkeys(doc["to"] + doc["cc"]))
        stored = self._ids | {"destination": doc["thread_id"], "item": copy.deepcopy(doc["item"])}
        doc["proposal"] = stored | {"recipients": recipients, "credits": 0}
        part = self._answer(user_id, doc, now_ms)
        if part is None:
            del doc["proposal"]
        return part

    def view(self, user_id: str, doc: dict[str, Any] | None) -> dict[str, Any] | None:
        """The card as it stands: its newest stored decision, or L1 (with its gate) when the last slot is a drop."""
        if doc is None or "policy_applied" not in doc:
            return doc
        return self._overlay(doc, self._head(user_id, doc)[1])

    def dropped(self, user_id: str, doc: dict[str, Any]) -> bool:
        return "policy_applied" in doc and self._head(user_id, doc)[1] is None

    @staticmethod
    def _overlay(doc: dict[str, Any], part: dict | None) -> dict[str, Any]:
        if part is None:  # `dropped` marks a card that held an L2 decision: its Cancel and Edit stop its key
            kept = {k: v for k, v in doc.items() if k not in ("policy_applied", "proposal")}
            gate = requested_part(doc, doc["outbox_id"])
            at_l1 = {"level": "L1", "undo_window_s": 0, "scheduled_at": None, "approval_requested": gate}
            return kept | at_l1 | {"dropped": True}
        data = part["data"]
        return doc | {"policy_applied": part, "policy_id": data["policy_id"], "undo_window_s": data["undo_window_s"]}

    def resolve(self, user_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        """The card to enqueue from: before any entry exists, a stale or unbound decision is made again or dropped.
        The new slot is created at the index of the head read that judged the old one; if another instance moved the
        head, the create fails and the loop reads again. No decision is recorded once the card's key is stored."""
        for _ in range(_ROUNDS):
            now = round(self._clock() * 1000)
            if "policy_applied" not in doc:
                return doc
            n, head = self._head(user_id, doc)
            card = self._overlay(doc, head)
            if head is None or card["level"] != "L2" or card["state"] != "open":
                return card
            if not self._ledger.ours(card) or self._ledger.holds(user_id, card["card_id"], "stop"):
                return card  # another world's, or stopped: `schedule` settles it
            bound = _bound(card, card["proposal"], self._ids["connector"])
            if self._ledger.stored(card) is not None or (bound and fresh(head["authz"].get("at"), now)):
                return card
            part = self._answer(user_id, card, now) if bound and n < MAX_REDECISIONS else None
            if self._ledger.stored(card) is not None:  # an enqueue landed while the engine was asked
                return card
            if self._cards.create(user_id, f"{card['card_id']}#pol{n + 1}", {"part": part} if part else {"drop": True}):
                if part is None and self._ledger.stored(card) is not None:  # an enqueue raced the drop: stop it first,
                    self._ledger.stop(user_id, card, "dropped")  # so the gate is never shown over a scheduled entry
                self._emit(copy.deepcopy(part) if part else requested_part(card, card["outbox_id"]))
        raise RuntimeError("the card's policy decision did not settle: retry")

    def _head(self, user_id: str, doc: dict[str, Any]) -> tuple[int, dict | None]:
        n, part = 0, doc["policy_applied"]
        while (slot := self._cards.get(user_id, f"{doc['card_id']}#pol{n + 1}")) is not None:
            n, part = n + 1, slot.get("part")
            if part is None:
                break
        return n, part

    def _answer(self, user_id: str, doc: dict[str, Any], now_ms: int) -> dict[str, Any] | None:
        stored = doc["proposal"]
        try:
            d = self._policy.decide(user_id, _proposal(stored))
        except Exception:
            return None
        authz = _usable(d, now_ms)
        if authz is None:
            return None
        part = {
            "type": "policy.applied",
            "authz": authz,
            "data": {
                "policy_id": d.policy_id,
                "gate_id": gate_id_for(doc["card_id"]),
                "outbox_id": doc["outbox_id"],
                "action_type": ACTION_TYPE,
                "connector": stored["connector"],
                "destination": stored["destination"],
                "district": stored["district"],
                "risk_tier": "T2",
                "level": "L2",
                "instruction_id": doc["instruction_id"],
                "undo_window_s": d.undo_window_s,
                "item": copy.deepcopy(stored["item"]),
                "credits": stored["credits"],
            },
        }
        return part if event_ok(part, ("policy.applied",)) and fresh(authz["at"], now_ms) else None
