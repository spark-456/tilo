"""Inbound WhatsApp dispatcher behind the signed webhook (FR-CHN-03, PRD 11.1, 10.3, 16.2).

A sender with no valid binding gets exactly one reply, the opt-in instructions, and nothing else runs:
no keyword effect, no card answer, no event. The text is the same for every unbound sender and message
and never echoes what was sent. A bound sender goes to the keyword handler (FR-CHN-06), then to the
card handler (FR-CHN-05); anything left is `unhandled` (FR-CHN-04 owns that reply).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from tilo_channels.keywords import Bindings, KeywordHandler
from tilo_channels.whatsapp import InboundMessage, mask_number

log = logging.getLogger("tilo_channels.inbound")


class Sender(Protocol):
    def send_text(self, to: str, body: str) -> object: ...


class _CardReply(Protocol):
    @property
    def outcome(self) -> str: ...


class CardHandler(Protocol):  # tilo_channels.cards.WhatsAppCards
    def handle(self, message: InboundMessage) -> _CardReply: ...


@dataclass(frozen=True)
class RouteResult:
    route: str  # "opt_in" | "keyword" | "card" | "unhandled"


def opt_in_text(web_url: str) -> str:
    return (
        "This number is not linked to Tilo. To get and answer Tilo cards here, sign in at "
        f"{web_url} and link your WhatsApp number."
    )


class InboundRouter:
    def __init__(
        self,
        *,
        bindings: Bindings,
        sender: Sender,
        web_url: str,
        keywords: KeywordHandler | None = None,
        cards: CardHandler | None = None,
    ) -> None:
        self._bindings = bindings
        self._sender = sender
        self._opt_in = opt_in_text(web_url)
        self._keywords = keywords
        self._cards = cards

    def __call__(self, message: InboundMessage) -> RouteResult:
        return self.handle(message)

    def handle(self, message: InboundMessage) -> RouteResult:
        if self._bindings.user_for(message.sender) is None:
            try:
                self._sender.send_text(message.sender, self._opt_in)
            except Exception as exc:
                log.error("opt-in reply failed to=%s error=%s", mask_number(message.sender), type(exc).__name__)
            return RouteResult("opt_in")
        if self._keywords is not None and self._keywords.handle(message).handled:
            return RouteResult("keyword")
        if self._cards is not None and self._cards.handle(message).outcome != "ignored":
            return RouteResult("card")
        return RouteResult("unhandled")
