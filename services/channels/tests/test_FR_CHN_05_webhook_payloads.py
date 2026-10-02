"""FR-CHN-05 webhook side: card answers arrive as Meta WhatsApp Cloud API button replies, behind the
signature-verified, idempotent webhook of FR-CHN-02 (PRD 11.6, 16.2, SEC-08).

A tap on an interactive reply button arrives as a message of type "interactive" with
`interactive.button_reply.{id,title}`; a tap on a template quick-reply button (the first message outside
the 24-hour window uses a pre-approved template, PRD 11.1) arrives as type "button" with
`button.{payload,text}`; `context.id` names the message replied to. The button id is the option Tilo put
on the card (channel.message_in: "option ... taken from the button's payload"); the title is display
text the person's client sends back and is never trusted.

Public interface: `tilo_channels.whatsapp.InboundMessage` gains `button_id` and `context_id`; the
end-to-end tests also use `tilo_channels.inbound.InboundRouter` and `tilo_channels.cards.WhatsAppCards`
(API_FR_CHN_03_05.md). Today the parsing tests fail on the missing fields and the end-to-end tests with
ModuleNotFoundError.
"""

from __future__ import annotations

import importlib
from typing import Any

from _channels_lib import MemoryDedupeStore, Recorder, delivery_body, make_app_secret, sign
from _chn_0305_lib import (
    MEETING,
    NUM_RIYA,
    QUESTION,
    WEB_URL,
    CardRig,
    button_reply,
    template_button,
    text_reply,
)
from tilo_channels.whatsapp import InboundMessage, WhatsAppWebhook


def _parse(rig_clock: Any, messages: list[dict]) -> list[Any]:
    secret = make_app_secret()
    recorder = Recorder()
    hook = WhatsAppWebhook(app_secret=secret, now=rig_clock, store=MemoryDedupeStore(rig_clock), handler=recorder)
    raw = delivery_body(messages)
    assert hook.receive(raw, sign(secret, raw)).status == 200
    return recorder.messages


# --- parsing ---------------------------------------------------------------------------------------


def test_FR_CHN_05_interactive_button_reply_is_parsed(clock: Any) -> None:
    ts = int(clock())
    [m] = _parse(clock, [button_reply("wamid.B1", NUM_RIYA, ts, "btn-opaque-1", "Approve", "wamid.OUTCARD000001")])
    assert m.kind == "interactive"
    assert m.button_id == "btn-opaque-1"
    assert m.context_id == "wamid.OUTCARD000001"
    assert m.text is None  # the title is display text, never treated as typed words


def test_FR_CHN_05_template_quick_reply_is_parsed(clock: Any) -> None:
    ts = int(clock())
    [m] = _parse(clock, [template_button("wamid.B2", NUM_RIYA, ts, "btn-opaque-2", "Hold", "wamid.OUTCARD000002")])
    assert m.kind == "button"
    assert m.button_id == "btn-opaque-2"
    assert m.context_id == "wamid.OUTCARD000002"
    assert m.text is None


def test_FR_CHN_05_text_reply_keeps_context_but_has_no_button(clock: Any) -> None:
    ts = int(clock())
    [m] = _parse(clock, [text_reply("wamid.B3", NUM_RIYA, ts, "approve", context_id="wamid.OUTCARD000003")])
    assert m.kind == "text" and m.text == "approve"
    assert m.button_id is None  # typed "approve" is not a button tap
    assert m.context_id == "wamid.OUTCARD000003"


def _malformed(ts: int) -> list[dict]:
    base = {"from": NUM_RIYA, "timestamp": str(ts), "type": "interactive"}
    return [
        base | {"id": "wamid.M1", "interactive": {"type": "list_reply", "list_reply": {"id": "x", "title": "x"}}},
        base | {"id": "wamid.M2", "interactive": {"type": "button_reply", "button_reply": {"id": 7, "title": "x"}}},
        base | {"id": "wamid.M3", "interactive": {"type": "button_reply", "button_reply": {"title": "Approve"}}},
        base | {"id": "wamid.M4", "interactive": {"type": "button_reply", "button_reply": {"id": "", "title": "x"}}},
        base | {"id": "wamid.M5", "interactive": "Approve"},
        base | {"id": "wamid.M6", "interactive": {"type": "button_reply", "button_reply": None}},
        {"from": NUM_RIYA, "timestamp": str(ts), "type": "button", "id": "wamid.M7", "button": {"payload": ["x"]}},
        base | {"id": "wamid.M8", "interactive": {"type": "button_reply", "button_reply": {"id": "b"}}, "context": "x"},
    ]


def test_FR_CHN_05_malformed_button_payloads_carry_no_button(clock: Any) -> None:
    messages = _parse(clock, _malformed(int(clock())))
    by_id = {m.message_id: m for m in messages}
    for mid in ("wamid.M1", "wamid.M2", "wamid.M3", "wamid.M4", "wamid.M5", "wamid.M6", "wamid.M7"):
        if mid in by_id:  # dropping a malformed message entirely is fine too
            assert by_id[mid].button_id is None, mid
    if "wamid.M8" in by_id:
        assert by_id["wamid.M8"].context_id is None  # a non-object context is ignored


def test_FR_CHN_05_inbound_message_new_fields_default_to_none() -> None:
    m = InboundMessage("wamid.X", NUM_RIYA, 0, "text", "hi")  # FR-CHN-02 positional form still works
    assert m.button_id is None and m.context_id is None


# --- end to end: signed webhook -> router -> cards ------------------------------------------------------


def _wire(rig: CardRig) -> tuple[WhatsAppWebhook, bytes]:
    inbound = importlib.import_module("tilo_channels.inbound")
    router = inbound.InboundRouter(bindings=rig.bindings, sender=rig.sender, web_url=WEB_URL, cards=rig.svc)
    secret = make_app_secret()
    hook = WhatsAppWebhook(app_secret=secret, now=rig.clock, store=MemoryDedupeStore(rig.clock), handler=router)
    return hook, secret


def test_FR_CHN_05_tap_through_signed_webhook_closes_web_card_within_2s() -> None:
    rig = CardRig()
    sent = rig.send(QUESTION)
    hook, secret = _wire(rig)
    button_id, title = sent["buttons"][1]  # per_pack
    raw = delivery_body([button_reply("wamid.T1", NUM_RIYA, int(rig.clock()), button_id, title, sent["message_id"])])
    received_at = rig.clock()
    response = hook.receive(raw, sign(secret, raw))
    assert response.status == 200 and [o.result for o in response.outcomes] == ["processed"]
    [call] = rig.api.accepted()
    assert call["option"] == "per_pack" and call["channel"] == "whatsapp"
    assert call["at"] - received_at <= 2.0  # PRD 11.6 FR-CHN-05: the web card closes in <= 2 s


def test_FR_CHN_05_replayed_tap_answers_once() -> None:
    rig = CardRig()
    sent = rig.send(MEETING)
    hook, secret = _wire(rig)
    button_id, title = sent["buttons"][0]
    raw = delivery_body([button_reply("wamid.T2", NUM_RIYA, int(rig.clock()), button_id, title, sent["message_id"])])
    first = hook.receive(raw, sign(secret, raw))
    replay = hook.receive(raw, sign(secret, raw))
    assert [o.result for o in first.outcomes] == ["processed"]
    assert [o.result for o in replay.outcomes] == ["duplicate"]
    assert len(rig.api.calls) == 1
    assert len(rig.events.of_type("channel.message_in")) == 1


def test_FR_CHN_05_forged_tap_is_rejected_before_any_answer() -> None:
    rig = CardRig()
    sent = rig.send(QUESTION)
    hook, _secret = _wire(rig)
    button_id, title = sent["buttons"][0]
    raw = delivery_body([button_reply("wamid.T3", NUM_RIYA, int(rig.clock()), button_id, title, sent["message_id"])])
    response = hook.receive(raw, sign(make_app_secret(), raw))  # signed with another secret
    assert response.status == 401
    assert rig.api.calls == [] and rig.events.of_type("channel.message_in") == []


def test_FR_CHN_05_spoofed_title_does_not_change_the_option() -> None:
    """The person's client echoes the title; only the button id Tilo issued decides the option."""
    rig = CardRig()
    sent = rig.send(QUESTION)
    hook, secret = _wire(rig)
    button_id, _ = sent["buttons"][0]  # per_kwh
    raw = delivery_body(
        [button_reply("wamid.T4", NUM_RIYA, int(rig.clock()), button_id, "Compare per pack", sent["message_id"])]
    )
    hook.receive(raw, sign(secret, raw))
    assert [c["option"] for c in rig.api.accepted()] == ["per_kwh"]
