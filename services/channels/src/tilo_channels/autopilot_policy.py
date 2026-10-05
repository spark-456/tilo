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
from datetime import UTC, datetime
from typing import Any

import tilo_policy
from tilo_policy.schemas import conforms, event_ok

from tilo_channels.autopilot_gate import gate_id_for, requested_part
from tilo_channels.autopilot_state import ACTION_TYPE, CardStore, Ledger

DECISION_MAX_AGE_S = 30  # a stored decision authorises a first enqueue at most this long after its `authz.at`
SKEW_S = 5  # a decision stamped this far ahead of our clock is still read as now
MAX_WINDOW_S = 86400
_ROUNDS = 3
_TIMESTAMP, _POLICY_ID = "common.schema.json#/$defs/timestamp", "common.schema.json#/$defs/policy_id"


def _ms(stamp: Any) -> int | None:
    if not isinstance(stamp, str) or not conforms(_TIMESTAMP, stamp):
        return None
    return round(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC).timestamp() * 1000)


def _usable(d: Any, now_ms: int) -> bool:
    """A clean decision for this card (BQ-248): run_after_undo, T2, L2, no modifier, a policy stamp naming a valid
    policy id, a readable `at` not ahead of us, and an int window of at least 1 s."""
    if not isinstance(d, tilo_policy.Decision):
        return False
    if (d.outcome, d.tier, d.level) != ("run_after_undo", "T2", "L2") or d.modifiers != ():
        return False
    stamp = d.authz.get("at") if isinstance(d.authz, dict) else None
    at, window = _ms(stamp), d.undo_window_s
    if at is None or at > now_ms + SKEW_S * 1000 or d.authz != {"by": "policy", "ref": d.policy_id, "at": stamp}:
        return False
    return conforms(_POLICY_ID, d.policy_id) and type(window) is int and 1 <= window <= MAX_WINDOW_S


def _fresh(part: dict, now_ms: int) -> bool:
    at = _ms(part["authz"].get("at"))
    return at is not None and -SKEW_S * 1000 <= now_ms - at <= DECISION_MAX_AGE_S * 1000


def _proposal(stored: dict) -> tilo_policy.Proposal:
    recipients = tuple(stored["recipients"])
    facts = tilo_policy.SideEffectFacts(recipients=recipients, known_recipients=recipients)
    keys = ("world_id", "action_type", "connector", "district", "destination", "item", "credits")
    return tilo_policy.Proposal(**{k: copy.deepcopy(stored[k]) for k in keys}, facts=facts, instruction=None)


def _bound(doc: dict, stored: dict) -> bool:
    """BQ-247: the card still says what the decision was made for."""
    return (
        doc["tier"] == "T2"
        and not doc["modifiers"]
        and bool(stored["recipients"])
        and tuple(dict.fromkeys(doc["to"] + doc["cc"])) == tuple(stored["recipients"])
        and doc["thread_id"] == stored["destination"]
        and doc["item"] == stored["item"]
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
        part = self._head(user_id, doc)[1]
        if part is None:
            kept = {k: v for k, v in doc.items() if k not in ("policy_applied", "proposal")}
            gate = requested_part(doc, doc["outbox_id"])
            return kept | {"level": "L1", "undo_window_s": 0, "scheduled_at": None, "approval_requested": gate}
        data = part["data"]
        return doc | {"policy_applied": part, "policy_id": data["policy_id"], "undo_window_s": data["undo_window_s"]}

    def resolve(self, user_id: str, doc: dict[str, Any]) -> dict[str, Any]:
        """The card to enqueue from: before any entry exists, a stale or unbound decision is made again or dropped."""
        for _ in range(_ROUNDS):
            now = round(self._clock() * 1000)
            card = self.view(user_id, doc) or doc
            if "policy_applied" not in card or card["level"] != "L2" or card["state"] != "open":
                return card
            if not self._ledger.ours(card) or self._ledger.holds(user_id, card["card_id"], "stop"):
                return card  # another world's, or stopped: `schedule` settles it
            if self._ledger.stored(card) is not None:
                return card
            bound = _bound(card, card["proposal"])
            if bound and _fresh(card["policy_applied"], now):
                return card
            part = self._answer(user_id, card, now) if bound else None
            slot = f"{card['card_id']}#pol{self._head(user_id, doc)[0] + 1}"
            if self._cards.create(user_id, slot, {"part": part} if part else {"drop": True}):
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
        if not _usable(d, now_ms):
            return None
        part = {
            "type": "policy.applied",
            "authz": copy.deepcopy(d.authz),
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
        return part if event_ok(part, ("policy.applied",)) and _fresh(part, now_ms) else None
