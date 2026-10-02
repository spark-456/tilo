"""FR-CHN-02 hardening (security review of #114): empty secret, wamid logging, payload shape,
pinned object/field/number id, future timestamps, stale logging, header encoding. Additive: the
pinned acceptance tests (fe8bb4e) are untouched. FR-CHN-06 covers the failed-keyword reply."""

from __future__ import annotations

import base64
import json
import logging

import pytest
from _channels_lib import (
    NUMBER_A,
    T0,
    FakeBindings,
    FakeClock,
    FakeControls,
    FakeSender,
    MemoryDedupeStore,
    Recorder,
    delivery_body,
    make_app_secret,
    sign,
    text_message,
    wamid,
)
from tilo_channels.keywords import FAILED_REPLY, KeywordHandler
from tilo_channels.whatsapp import WhatsAppWebhook, message_ref, verify_signature


def _hook(*, handler=None, secret=None, **kwargs):
    secret = secret if secret is not None else make_app_secret()
    clock = FakeClock(T0 + 60)
    handler = handler if handler is not None else Recorder()
    hook = WhatsAppWebhook(app_secret=secret, now=clock, store=MemoryDedupeStore(clock), handler=handler, **kwargs)
    return hook, handler, secret, clock


def _post(hook, secret, payload):
    body = json.dumps(payload).encode("utf-8")
    return hook.receive(body, sign(secret, body))


def _payload(messages, *, obj="whatsapp_business_account", field="messages", number_id="pn-1"):
    value = {"metadata": {"phone_number_id": number_id}, "messages": messages}
    return {"object": obj, "entry": [{"changes": [{"field": field, "value": value}]}]}


def _msg(n=1, ts=T0 + 30, body="hello"):
    return text_message(wamid(n), NUMBER_A, ts, body)


@pytest.mark.parametrize("secret", [b"", b"short", b"x" * 31])
def test_FR_CHN_02_short_or_empty_app_secret_is_refused_at_construction(secret):
    clock = FakeClock()
    with pytest.raises(ValueError):
        WhatsAppWebhook(app_secret=secret, now=clock, store=MemoryDedupeStore(clock), handler=Recorder())


def test_FR_CHN_02_empty_key_never_verifies():
    body = delivery_body([_msg()])
    assert verify_signature(b"", body, sign(b"", body)) is False


def test_FR_CHN_02_non_ascii_signature_header_is_false_not_an_error():
    body = delivery_body([_msg()])
    assert verify_signature(make_app_secret(), body, "sha256=\ud800abc") is False
    assert verify_signature(make_app_secret(), body, "sha256=é") is False


def _meta_style_wamid(number: str) -> str:
    record = b"\x1c\x18\x0b" + number.encode("ascii") + b"\x15\x02\x00\x12\x04" + b"A1B2C3D4E5F6"
    return "wamid." + base64.b64encode(record).decode("ascii").rstrip("=")


def test_FR_CHN_02_logs_carry_neither_the_number_nor_the_raw_wamid(caplog):
    number = "16503879439"
    real_id = _meta_style_wamid(number)
    assert number in base64.b64decode(real_id[6:] + "==").decode("latin-1")

    def boom(_message):
        raise RuntimeError("no")

    hook, _, secret, _ = _hook(handler=boom)
    stale = text_message(_meta_style_wamid("16503879440"), "16503879440", T0 - 1000, "x")
    with caplog.at_level(logging.DEBUG, logger="tilo_channels"):
        _post(hook, secret, _payload([text_message(real_id, number, T0 + 30, "hi"), stale]))
    logged = caplog.text
    assert "failed" in logged and "stale" in logged
    for forbidden in (number, "16503879440", real_id, real_id[6:], base64.b64encode(number.encode()).decode()[:8]):
        assert forbidden not in logged
    assert message_ref(real_id) in logged
    assert message_ref(real_id) != real_id and len(message_ref(real_id)) == 12


@pytest.mark.parametrize(
    "payload",
    [
        {"object": "whatsapp_business_account", "entry": 5},
        {"object": "whatsapp_business_account", "entry": [{"changes": 7}]},
        {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": []}]}]},
        {"object": "whatsapp_business_account", "entry": ["x", None, {"changes": [None, 3]}]},
        _payload(3),
        _payload({"a": 1}),
    ],
)
def test_FR_CHN_02_oddly_shaped_signed_bodies_are_skipped_not_a_500(payload):
    hook, handler, secret, _ = _hook()
    response = _post(hook, secret, payload)
    assert response.status == 200 and response.outcomes == () and handler.messages == []


def test_FR_CHN_02_overflowing_timestamp_is_skipped():
    hook, handler, secret, _ = _hook()
    body = delivery_body([_msg()]).replace(b'"%d"' % (T0 + 30), b"1e400")
    assert b"1e400" in body
    response = hook.receive(body, sign(secret, body))
    assert response.status == 200 and response.outcomes == () and handler.messages == []


@pytest.mark.parametrize(
    "payload",
    [
        _payload([_msg()], obj="page"),
        _payload([_msg()], field="other"),
        _payload([_msg()], number_id="pn-foreign"),
    ],
)
def test_FR_CHN_02_object_field_and_number_id_are_pinned(payload):
    hook, handler, secret, _ = _hook(phone_number_id="pn-1")
    response = _post(hook, secret, payload)
    assert response.status == 200 and response.outcomes == () and handler.messages == []


def test_FR_CHN_02_pinned_number_id_accepts_its_own_messages():
    hook, handler, secret, _ = _hook(phone_number_id="pn-1")
    response = _post(hook, secret, _payload([_msg()]))
    assert [o.result for o in response.outcomes] == ["processed"] and handler.ids() == [wamid(1)]


def test_FR_CHN_02_future_timestamps_beyond_the_skew_are_dropped_without_a_claim():
    hook, handler, secret, clock = _hook()
    now = clock()
    ok = _msg(1, int(now) + 30)
    too_far = _msg(2, int(now) + 120)
    response = _post(hook, secret, _payload([ok, too_far]))
    assert [o.result for o in response.outcomes] == ["processed", "stale"]
    assert handler.ids() == [wamid(1)]


def test_FR_CHN_02_future_skew_is_configurable():
    hook, handler, secret, clock = _hook(max_future_skew_s=200)
    response = _post(hook, secret, _payload([_msg(2, int(clock()) + 120)]))
    assert [o.result for o in response.outcomes] == ["processed"]


def test_FR_CHN_06_failed_keyword_effect_sends_one_short_reply():
    clock = FakeClock()
    controls, sender = FakeControls(clock), FakeSender(clock)
    controls.fail.add("stop_all_autopilot")
    handler = KeywordHandler(bindings=FakeBindings(), controls=controls, sender=sender)
    from tilo_channels.whatsapp import InboundMessage

    result = handler.handle(InboundMessage(wamid(1), NUMBER_A, T0, "text", "stop autopilot"))
    assert (result.handled, result.applied, result.confirmed) == (True, False, False)
    assert sender.bodies_to(NUMBER_A) == [FAILED_REPLY]
    assert FAILED_REPLY == "Could not apply that. Use Stop all in the app."
