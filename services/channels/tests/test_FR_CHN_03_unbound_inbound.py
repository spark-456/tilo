"""FR-CHN-03 acceptance test (PRD 11.6): "Unbound numbers get only the opt-in instructions."

PRD 11.1: "Only bound numbers can give commands." PRD 10.3: WhatsApp cards are answered "only from the
user's verified, bound number". PRD 16.2: spoofed WhatsApp commands are stopped by the signature check
and "bound numbers only". A number is unbound when it was never bound, is still pending its code, has
passed its 30-day re-confirmation, or was unbound.

Public interface: `tilo_channels.inbound.InboundRouter` in front of `tilo_channels.keywords` (FR-CHN-06)
and `tilo_channels.cards` (FR-CHN-05), with `tilo_channels.binding.BindingService` as the binding source
(API_FR_CHN_03_05.md). Those modules do not exist yet, so this file fails at collection.

"Only the opt-in instructions" is read as: exactly one reply per inbound message, the opt-in text, which
points to the web app (the binding screen, PRD 11.1, S-16), is the same whatever was sent, and never
echoes the message; nothing else happens: no keyword effect, no card answer, no event (BQ-89).
"""

from __future__ import annotations

import importlib
import re
from typing import Any

import pytest
from _channels_lib import (
    FakeClock,
    FakeControls,
    MemoryDedupeStore,
    delivery_body,
    image_message,
    make_app_secret,
    sign,
    text_message,
)
from _chn_0305_lib import (
    GATE_T1,
    NUM_RIYA,
    NUM_STRANGER,
    RIYA,
    THIRTY_DAYS_S,
    WEB_URL,
    FakeArchive,
    FakeBindingStore,
    FakeCardsApi,
    FakeCardSender,
    FakeCipher,
    FakeEventWriter,
    FakePins,
    fake_key,
    fake_pin,
    make_card,
)
from tilo_channels.keywords import KeywordHandler
from tilo_channels.whatsapp import InboundMessage, WhatsAppWebhook

_CODE = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _mod(name: str) -> Any:
    """Modules under test, imported at call time so each test fails on its own until they exist."""
    return importlib.import_module(f"tilo_channels.{name}")


class World:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.sender = FakeCardSender(self.clock)
        self.bindings = _mod("binding").BindingService(
            store=FakeBindingStore(), cipher=FakeCipher(), sender=self.sender, clock=self.clock, hash_key=fake_key()
        )
        self.controls = FakeControls(self.clock)
        self.card = make_card(GATE_T1, created_at=self.clock())
        self.api = FakeCardsApi(self.clock, {GATE_T1: self.card})
        self.events = FakeEventWriter()
        self.archive = FakeArchive()
        self.cards = _mod("cards").WhatsAppCards(
            bindings=self.bindings,
            api=self.api,
            sender=self.sender,
            events=self.events,
            archive=self.archive,
            pins=FakePins({RIYA: fake_pin()}),
            clock=self.clock,
            web_url=WEB_URL,
        )
        self.router = _mod("inbound").InboundRouter(
            bindings=self.bindings,
            sender=self.sender,
            web_url=WEB_URL,
            keywords=KeywordHandler(bindings=self.bindings, controls=self.controls, sender=self.sender),
            cards=self.cards,
        )
        self._n = 0

    def bind_riya(self) -> None:
        assert self.bindings.start(RIYA, NUM_RIYA).ok
        code = _CODE.findall(self.sender.texts_to(NUM_RIYA)[-1])[0]
        assert self.bindings.confirm(RIYA, code).ok

    def send_riya_card(self) -> dict[str, Any]:
        assert self.cards.send_card(self.card, user_id=RIYA).outcome == "sent"
        return self.sender.cards[-1]

    def msg(self, sender: str, *, kind: str = "text", text: str | None = None, **extra: Any) -> InboundMessage:
        self._n += 1
        return InboundMessage(f"wamid.IN{self._n:06d}", sender, int(self.clock()), kind, text, **extra)

    def snapshot(self) -> tuple[int, int, int, int]:
        return len(self.controls.calls), len(self.api.calls), len(self.events.parts), len(self.sender.cards)


@pytest.fixture()
def world() -> World:
    w = World()
    w.bind_riya()
    return w


def _assert_only_opt_in(world: World, number: str, before: tuple, texts_before: int, inbound_text: str | None) -> str:
    replies = world.sender.texts_to(number)[texts_before:]
    assert len(replies) == 1, "exactly one reply: the opt-in instructions"
    reply = replies[0]
    assert WEB_URL in reply
    if inbound_text:
        assert inbound_text not in reply
    assert world.snapshot() == before, "an unbound number must cause nothing but the opt-in reply"
    return reply


def _cases(world: World, riya_card: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    button_id, title = riya_card["buttons"][0]
    return [
        ("text", {"text": "hello, what can you do?"}),
        ("text", {"text": "STOP AUTOPILOT"}),
        ("text", {"text": "PAUSE"}),
        ("text", {"text": "UNSUBSCRIBE"}),
        ("text", {"text": "approve"}),
        ("image", {}),
        ("interactive", {"button_id": button_id, "context_id": riya_card["message_id"]}),
        ("button", {"button_id": button_id, "context_id": riya_card["message_id"]}),
    ]


def test_FR_CHN_03_unbound_numbers_get_only_the_opt_in_instructions(world: World) -> None:
    riya_card = world.send_riya_card()
    replies = []
    for kind, fields in _cases(world, riya_card):
        before, texts_before = world.snapshot(), len(world.sender.texts_to(NUM_STRANGER))
        result = world.router.handle(world.msg(NUM_STRANGER, kind=kind, **fields))
        assert result.route == "opt_in", (kind, fields)
        replies.append(_assert_only_opt_in(world, NUM_STRANGER, before, texts_before, fields.get("text")))
    assert len(set(replies)) == 1, "the same opt-in text whatever was sent"
    assert world.api.accepted() == []
    assert world.controls.calls == []


def test_FR_CHN_03_pending_number_is_unbound_until_confirmed() -> None:
    world = World()
    assert world.bindings.start(RIYA, NUM_RIYA).ok  # code sent, never confirmed
    before, texts_before = world.snapshot(), len(world.sender.texts_to(NUM_RIYA))
    result = world.router.handle(world.msg(NUM_RIYA, text="STOP AUTOPILOT"))
    assert result.route == "opt_in"
    _assert_only_opt_in(world, NUM_RIYA, before, texts_before, "STOP AUTOPILOT")


def test_FR_CHN_03_expired_binding_gets_only_opt_in_and_cannot_answer(world: World) -> None:
    riya_card = world.send_riya_card()
    world.clock.advance(THIRTY_DAYS_S)
    before, texts_before = world.snapshot(), len(world.sender.texts_to(NUM_RIYA))
    button_id, _ = riya_card["buttons"][0]
    tap = world.msg(NUM_RIYA, kind="interactive", button_id=button_id, context_id=riya_card["message_id"])
    assert world.router.handle(tap).route == "opt_in"
    _assert_only_opt_in(world, NUM_RIYA, before, texts_before, None)
    assert world.api.calls == []


def test_FR_CHN_03_unbound_number_cannot_answer_its_old_card(world: World) -> None:
    riya_card = world.send_riya_card()
    assert world.bindings.unbind(RIYA)
    before, texts_before = world.snapshot(), len(world.sender.texts_to(NUM_RIYA))
    button_id, _ = riya_card["buttons"][0]
    tap = world.msg(NUM_RIYA, kind="interactive", button_id=button_id, context_id=riya_card["message_id"])
    assert world.router.handle(tap).route == "opt_in"
    _assert_only_opt_in(world, NUM_RIYA, before, texts_before, None)
    assert world.api.calls == []


def test_FR_CHN_03_bound_number_does_not_get_the_opt_in_text(world: World) -> None:
    stranger_before = len(world.sender.texts_to(NUM_STRANGER))
    world.router.handle(world.msg(NUM_STRANGER, text="hi"))
    opt_in = world.sender.texts_to(NUM_STRANGER)[stranger_before]
    riya_before = len(world.sender.texts_to(NUM_RIYA))
    result = world.router.handle(world.msg(NUM_RIYA, text="what's the status of my supplier summary?"))
    assert result.route != "opt_in"
    assert opt_in not in world.sender.texts_to(NUM_RIYA)[riya_before:]


def test_FR_CHN_03_bound_number_keyword_still_works(world: World) -> None:
    result = world.router.handle(world.msg(NUM_RIYA, text="PAUSE"))
    assert result.route == "keyword"
    assert world.controls.methods() == ["pause_all"]


def test_FR_CHN_03_opt_in_through_the_signed_webhook() -> None:
    """End to end behind the FR-CHN-02 webhook: a signed delivery from an unbound number."""
    world = World()
    world.bind_riya()
    secret = make_app_secret()
    hook = WhatsAppWebhook(
        app_secret=secret, now=world.clock, store=MemoryDedupeStore(world.clock), handler=world.router
    )
    ts = int(world.clock())
    raw = delivery_body(
        [
            text_message("wamid.E2E1", NUM_STRANGER, ts, "STOP AUTOPILOT"),
            image_message("wamid.E2E2", NUM_STRANGER, ts),
        ]
    )
    before = world.snapshot()
    response = hook.receive(raw, sign(secret, raw))
    assert response.status == 200
    assert [o.result for o in response.outcomes] == ["processed", "processed"]
    replies = world.sender.texts_to(NUM_STRANGER)
    assert len(replies) == 2 and len(set(replies)) == 1 and WEB_URL in replies[0]
    assert world.snapshot() == before
