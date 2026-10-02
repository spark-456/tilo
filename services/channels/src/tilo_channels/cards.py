"""Cards as interactive WhatsApp messages; answers sync to every channel (FR-CHN-05, PRD 10.3, SEC-06).

A card goes out as one message with one reply button per option (labels as on the card, opaque random
ids). A tap is honoured only from the number the card was sent to while it is still bound to the card's
user, and is passed to tilo-api, which records the answer (first answer wins) and closes the web card.
Approve on a T3 gate first asks for the PIN: the next text from that number within `pin_window_s` is
checked, one try per tap, and only then is the answer sent with `pin_verified=True`. Typed text never
answers a card option (BQ-56). Channels writes only `channel.message_out` and `channel.message_in`; the
API emits `question.answered` and `approval.resolved`. Numbers and PINs are never logged, archived or
put in events. Defaults the PRD leaves open are BQ-89.
"""

from __future__ import annotations

import datetime as dt
import logging
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from tilo_channels.whatsapp import InboundMessage, mask_number, message_ref

log = logging.getLogger("tilo_channels.cards")

PIN_WINDOW_S = 300
CHANNEL = "whatsapp"


class CardsApi(Protocol):
    def answer(
        self, world_id: str, card_id: str, *, option: str, user_id: str, channel: str, pin_verified: bool
    ) -> Any: ...


class PinVerifier(Protocol):
    def verify(self, user_id: str, pin: str) -> bool: ...


class Archive(Protocol):
    def record(self, run_id: str, kind: str, payload: Mapping[str, Any]) -> str: ...


class EventWriter(Protocol):
    def write(self, part: dict[str, Any]) -> None: ...


class CardSender(Protocol):
    def send_text(self, to: str, body: str) -> object: ...
    def send_buttons(self, to: str, body: str, buttons: Sequence[tuple[str, str]]) -> str: ...


class CardBindings(Protocol):
    def user_for(self, number: str) -> str | None: ...
    def number_for(self, user_id: str) -> str | None: ...


@dataclass(frozen=True)
class SendResult:
    outcome: str  # "sent" | "not_bound" | "not_whatsapp" | "expired"
    message_id: str | None


@dataclass(frozen=True)
class ReplyResult:
    outcome: str  # see API_FR_CHN_03_05.md
    card_id: str | None
    option: str | None


@dataclass
class _Sent:
    card: Mapping[str, Any]
    user_id: str
    number: str
    deadline: float
    open: bool = True
    labels: dict[str, str] = field(default_factory=dict)


_IGNORED = ReplyResult("ignored", None, None)


def _deadline(card: Mapping[str, Any]) -> float:
    created = dt.datetime.fromisoformat(str(card["created_at"]).replace("Z", "+00:00"))
    return created.timestamp() + float(card["timeout"])


def _needs_pin(card: Mapping[str, Any], option: str) -> bool:
    gate = card.get("gate")
    return option == "approve" and isinstance(gate, Mapping) and gate.get("risk_tier") == "T3"


class WhatsAppCards:
    def __init__(
        self,
        *,
        bindings: CardBindings,
        api: CardsApi,
        sender: CardSender,
        events: EventWriter,
        archive: Archive,
        pins: PinVerifier,
        clock: Callable[[], float],
        web_url: str,
        pin_window_s: float = PIN_WINDOW_S,
    ) -> None:
        self._bindings = bindings
        self._api = api
        self._sender = sender
        self._events = events
        self._archive = archive
        self._pins = pins
        self._clock = clock
        self._web_url = web_url.rstrip("/")
        self._pin_window_s = pin_window_s
        self._lock = threading.Lock()
        self._sent: dict[str, _Sent] = {}  # card_id -> sent record
        self._buttons: dict[str, tuple[str, str]] = {}  # button id -> (card_id, option)
        self._pin_prompts: dict[str, tuple[str, float]] = {}  # number -> (card_id, asked_at)

    def send_card(self, card: Mapping[str, Any], *, user_id: str) -> SendResult:
        if CHANNEL not in card.get("answer_channels", ()):
            return SendResult("not_whatsapp", None)
        number = self._bindings.number_for(user_id)
        if number is None:
            return SendResult("not_bound", None)
        deadline = _deadline(card)
        if self._clock() >= deadline:
            return SendResult("expired", None)
        card_id = str(card["id"])
        buttons = [(f"tc1.{secrets.token_urlsafe(18)}", str(o["label"])) for o in card["options"]]
        link = f"{self._web_url}/worlds/{card['world_id']}/cards/{card_id}"
        body = f"{card['what_happened']}\n{card['why_it_matters']}\n\nOpen in Tilo: {link}"
        message_id = self._sender.send_buttons(number, body, buttons)
        sent = _Sent(card, user_id, number, deadline, labels={o["id"]: o["label"] for o in card["options"]})
        with self._lock:
            self._sent[card_id] = sent
            for (button_id, _), option in zip(buttons, card["options"], strict=True):
                self._buttons[button_id] = (card_id, str(option["id"]))
        ref = self._archive.record(card["run_id"], "whatsapp.card_out", {"channel": CHANNEL, "card_id": card_id})
        self._event(card, "channel.message_out", "system", {"channel": CHANNEL, "message_ref": ref, "card_id": card_id})
        return SendResult("sent", message_id)

    def handle(self, message: InboundMessage) -> ReplyResult:
        user_id = self._bindings.user_for(message.sender)
        if user_id is None:
            return _IGNORED  # the router sends the opt-in text (FR-CHN-03)
        if message.button_id is not None:
            return self._tap(message, user_id, message.button_id)
        if message.kind == "text":
            return self._pin_reply(message, user_id)
        return _IGNORED

    def card_closed(self, card_id: str, *, channel: str) -> bool:
        with self._lock:
            sent = self._sent.get(card_id)
            if sent is None or not sent.open:
                return False
            sent.open = False
        if channel == CHANNEL:
            return False
        if self._bindings.user_for(sent.number) == sent.user_id:
            reason = "it timed out" if channel == "timeout" else "it was answered in Tilo"
            self._say(sent.number, f"This card is closed: {reason}. Nothing more is needed here.")
        return True

    # --- inbound ------------------------------------------------------------------------------------

    def _tap(self, message: InboundMessage, user_id: str, button_id: str) -> ReplyResult:
        with self._lock:
            found = self._buttons.get(button_id)
            sent = self._sent.get(found[0]) if found else None
        if found is None or sent is None:
            return self._refuse(message, "unknown_card", None, None, "That button is not from a current Tilo card.")
        card_id, option = found
        if message.sender != sent.number or user_id != sent.user_id:
            return self._refuse(message, "forbidden", None, None, "This card was not sent to this number.")
        refused = self._closed_or_expired(message, sent, card_id, option)
        if refused is not None:
            return refused
        if _needs_pin(sent.card, option):
            with self._lock:
                self._pin_prompts[message.sender] = (card_id, self._clock())
            minutes = int(self._pin_window_s // 60)
            text = f"To approve, reply with your Tilo PIN within {minutes} minutes. Nothing happens until then."
            return self._refuse(message, "pin_required", card_id, option, text)
        return self._answer(message, sent, card_id, option, pin_verified=False)

    def _pin_reply(self, message: InboundMessage, user_id: str) -> ReplyResult:
        with self._lock:
            prompt = self._pin_prompts.pop(message.sender, None)
            sent = self._sent.get(prompt[0]) if prompt else None
        if prompt is None or sent is None or self._clock() >= prompt[1] + self._pin_window_s:
            return _IGNORED
        card_id = prompt[0]
        if user_id != sent.user_id:
            return self._refuse(message, "forbidden", card_id, None, "This card was not sent to this number.")
        refused = self._closed_or_expired(message, sent, card_id, "approve")
        if refused is not None:
            return refused
        try:
            verified = self._pins.verify(sent.user_id, (message.text or "").strip())
        except Exception as exc:
            log.error("pin check failed card=%s error=%s", card_id, type(exc).__name__)
            return self._refuse(message, "failed", card_id, "approve", "Could not check the PIN. Tap Approve again.")
        if not verified:
            return self._refuse(message, "wrong_pin", card_id, "approve", "Wrong PIN. Nothing was approved.")
        return self._answer(message, sent, card_id, "approve", pin_verified=True)

    def _closed_or_expired(self, message: InboundMessage, sent: _Sent, card_id: str, option: str) -> ReplyResult | None:
        if not sent.open:
            return self._refuse(message, "already_answered", card_id, option, "This card was already answered.")
        if self._clock() >= sent.deadline:
            return self._refuse(message, "expired", card_id, option, "This card has timed out.")
        return None

    def _answer(
        self, message: InboundMessage, sent: _Sent, card_id: str, option: str, *, pin_verified: bool
    ) -> ReplyResult:
        card = sent.card
        try:
            result = self._api.answer(
                str(card["world_id"]),
                card_id,
                option=option,
                user_id=sent.user_id,
                channel=CHANNEL,
                pin_verified=pin_verified,
            )
        except Exception as exc:
            log.error("card answer failed card=%s error=%s", card_id, type(exc).__name__)
            return self._refuse(message, "failed", card_id, option, "Could not record your answer. Try again.")
        if getattr(result, "outcome", None) != "answered":
            if getattr(result, "reason", None) == "already_resolved":
                sent.open = False
                return self._refuse(message, "already_answered", card_id, option, "This card was already answered.")
            log.warning("card answer rejected card=%s reason=%s", card_id, getattr(result, "reason", None))
            return self._refuse(message, "rejected", card_id, option, "Tilo could not take that answer.")
        sent.open = False
        self._record_answer(message, sent, card_id, option)
        self._say(message.sender, f"Done: {sent.labels.get(option, option)}.")
        return ReplyResult("answered", card_id, option)

    def _record_answer(self, message: InboundMessage, sent: _Sent, card_id: str, option: str) -> None:
        card = sent.card
        gate = card.get("gate")
        destination = gate["action"]["destination"] if card["kind"] == "gate" and isinstance(gate, Mapping) else None
        payload = {"channel": CHANNEL, "card_id": card_id, "option": option, "message": message_ref(message.message_id)}
        try:
            ref = self._archive.record(card["run_id"], "whatsapp.card_answer", payload)
            data = {
                "channel": CHANNEL,
                "message_ref": ref,
                "card_id": card_id,
                "card_kind": card["kind"],
                "option": option,
                "destination": destination,
            }
            self._event(card, "channel.message_in", sent.user_id, data)
        except Exception as exc:  # the API already recorded the answer; tell the person anyway
            log.error("card answer record failed card=%s error=%s", card_id, type(exc).__name__)

    # --- outbound -------------------------------------------------------------------------------------

    def _event(self, card: Mapping[str, Any], event_type: str, actor: str, data: dict[str, Any]) -> None:
        part = {
            "type": event_type,
            "world_id": card["world_id"],
            "run_id": card["run_id"],
            "actor": actor,
            "authz": None,
            "data": data,
        }
        self._events.write(part)

    def _refuse(
        self, message: InboundMessage, outcome: str, card_id: str | None, option: str | None, text: str
    ) -> ReplyResult:
        self._say(message.sender, text)
        return ReplyResult(outcome, card_id, option)

    def _say(self, to: str, body: str) -> None:
        try:
            self._sender.send_text(to, body)
        except Exception as exc:
            log.error("whatsapp text failed to=%s error=%s", mask_number(to), type(exc).__name__)
