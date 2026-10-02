"""WhatsApp keywords STOP AUTOPILOT, PAUSE, UNSUBSCRIBE (FR-CHN-06, PRD 11.1, 10.4).

The effect goes through the injected control plane (the tilo-api client in production; channels
never writes business state). Only numbers bound to a user are obeyed. The confirmation is sent
after the effect, to the sender, once.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from tilo_channels.whatsapp import InboundMessage, Sender, mask_number

log = logging.getLogger("tilo_channels.keywords")

STOP_AUTOPILOT = "STOP AUTOPILOT"
PAUSE = "PAUSE"
UNSUBSCRIBE = "UNSUBSCRIBE"
_KEYWORDS = frozenset({STOP_AUTOPILOT, PAUSE, UNSUBSCRIBE})
CHANNEL = "whatsapp"
FAILED_REPLY = "Could not apply that. Use Stop all in the app."


class Bindings(Protocol):
    def user_for(self, number: str) -> str | None: ...


class Controls(Protocol):
    def stop_all_autopilot(self, user_id: str, *, channel: str) -> int: ...
    def pause_all(self, user_id: str, *, channel: str) -> None: ...
    def unsubscribe_whatsapp(self, user_id: str) -> None: ...


@dataclass(frozen=True)
class KeywordResult:
    handled: bool
    keyword: str | None
    applied: bool
    confirmed: bool


def parse_keyword(text: str | None) -> str | None:
    """The whole message must be the keyword: case-insensitive, whitespace trimmed and collapsed."""
    if text is None or not text.isascii():
        return None
    candidate = " ".join(text.split()).upper()
    return candidate if candidate in _KEYWORDS else None


class KeywordHandler:
    def __init__(self, *, bindings: Bindings, controls: Controls, sender: Sender) -> None:
        self._bindings = bindings
        self._controls = controls
        self._sender = sender

    def handle(self, message: InboundMessage) -> KeywordResult:
        keyword = parse_keyword(message.text) if message.kind == "text" else None
        if keyword is None:
            return KeywordResult(False, None, False, False)
        user_id = self._bindings.user_for(message.sender)
        if user_id is None:  # not bound: not obeyed, not answered; the dispatcher continues
            return KeywordResult(False, keyword, False, False)
        try:
            confirmation = self._apply(keyword, user_id)
        except Exception as exc:
            log.error("keyword effect failed keyword=%s error=%s", keyword, type(exc).__name__)
            self._reply(message.sender, keyword, FAILED_REPLY)
            return KeywordResult(True, keyword, False, False)
        confirmed = self._reply(message.sender, keyword, confirmation)
        return KeywordResult(True, keyword, True, confirmed)

    def _reply(self, to: str, keyword: str, body: str) -> bool:
        try:
            self._sender.send_text(to, body)
        except Exception as exc:
            log.error("keyword reply failed keyword=%s to=%s error=%s", keyword, mask_number(to), type(exc).__name__)
            return False
        return True

    def _apply(self, keyword: str, user_id: str) -> str:
        if keyword == STOP_AUTOPILOT:
            count = self._controls.stop_all_autopilot(user_id, channel=CHANNEL)
            return f"Autopilot stopped: {count} of your policies now ask you first. Your agents keep running."
        if keyword == PAUSE:
            self._controls.pause_all(user_id, channel=CHANNEL)
            return "Paused: all your agents are paused. Resume from the Tilo app."
        self._controls.unsubscribe_whatsapp(user_id)
        return "You are unsubscribed from Tilo WhatsApp messages. This is the last one."
