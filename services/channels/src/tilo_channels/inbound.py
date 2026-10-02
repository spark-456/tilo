"""Inbound WhatsApp dispatcher behind the signed webhook (FR-CHN-03, PRD 11.1, 10.3, 16.2).

A sender with no valid binding gets exactly one reply, the opt-in instructions, and nothing else runs:
no keyword effect, no card answer, no event. The text is the same for every unbound sender and message
and never echoes what was sent. A bound sender goes to the keyword handler (FR-CHN-06), then to the
card handler (FR-CHN-05); anything left is `off_topic` (FR-CHN-04): one fixed redirect line to the sender,
no model call, no archive record, no event, nothing echoed. A handler that raises gives route `failed`
and one short reply. `opt_in_allowed` (BindingService.allow_opt_in in production)
rate-limits the opt-in reply per number; without it every unbound message gets one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from tilo_channels.keywords import Bindings, KeywordHandler
from tilo_channels.whatsapp import InboundMessage, Sender, mask_number, message_ref

log = logging.getLogger("tilo_channels.inbound")


class _CardReply(Protocol):
    @property
    def outcome(self) -> str: ...


class CardHandler(Protocol):  # tilo_channels.cards.WhatsAppCards
    def handle(self, message: InboundMessage) -> _CardReply: ...


@dataclass(frozen=True)
class RouteResult:
    route: str  # "opt_in" | "keyword" | "card" | "off_topic" | "failed"


FAILED_TEXT = "Something went wrong with that message. Please check Tilo."


def opt_in_text(web_url: str) -> str:
    return (
        "This number is not linked to Tilo. To get and answer Tilo cards here, sign in at "
        f"{web_url} and link your WhatsApp number."
    )


def off_topic_text(web_url: str) -> str:
    return (
        "I'm Tilo's automated assistant and I only help with your Tilo tasks and cards; "
        f"for anything else, open {web_url}."
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
        opt_in_allowed: Callable[[str], bool] | None = None,
    ) -> None:
        self._opt_in_allowed = opt_in_allowed
        self._bindings = bindings
        self._sender = sender
        self._opt_in = opt_in_text(web_url)
        self._off_topic = off_topic_text(web_url)
        self._keywords = keywords
        self._cards = cards

    def __call__(self, message: InboundMessage) -> RouteResult:
        return self.handle(message)

    def handle(self, message: InboundMessage) -> RouteResult:
        if self._bindings.user_for(message.sender) is None:
            if self._opt_in_allowed is None or self._opt_in_allowed(message.sender):
                self._say(message.sender, self._opt_in)
            return RouteResult("opt_in")
        try:
            if self._keywords is not None and self._keywords.handle(message).handled:
                return RouteResult("keyword")
            if self._cards is not None and self._cards.handle(message).outcome != "ignored":
                return RouteResult("card")
        except Exception as exc:
            log.error("inbound handler failed ref=%s error=%s", message_ref(message.message_id), type(exc).__name__)
            self._say(message.sender, FAILED_TEXT)
            return RouteResult("failed")
        self._say(message.sender, self._off_topic)
        return RouteResult("off_topic")

    def _say(self, to: str, body: str) -> None:
        try:
            self._sender.send_text(to, body)
        except Exception as exc:
            log.error("inbound reply failed to=%s error=%s", mask_number(to), type(exc).__name__)
