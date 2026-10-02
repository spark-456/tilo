"""FR-CHN-02 addition: what the webhook does when the handler raises (decision recorded in
services/channels/CLAUDE.md): the dedupe claim is kept (at-most-once), the outcome is "failed",
the webhook still answers 200 (Meta retries non-2xx) and the log carries no message text."""

from __future__ import annotations

import logging

from _channels_lib import (
    NUMBER_A,
    T0,
    FakeClock,
    MemoryDedupeStore,
    delivery_body,
    make_app_secret,
    sign,
    text_message,
    wamid,
)
from tilo_channels.whatsapp import WhatsAppWebhook

SECRET_TEXT = "private words 12345"


def test_FR_CHN_02_handler_error_keeps_the_claim_and_answers_200(caplog):
    secret = make_app_secret()
    clock = FakeClock(T0 + 60)
    calls: list[str] = []

    def boom(message):
        calls.append(message.message_id)
        raise RuntimeError(f"cannot handle {message.text}")

    hook = WhatsAppWebhook(app_secret=secret, now=clock, store=MemoryDedupeStore(clock), handler=boom)
    body = delivery_body([text_message(wamid(1), NUMBER_A, T0 + 30, SECRET_TEXT)])
    header = sign(secret, body)
    with caplog.at_level(logging.DEBUG, logger="tilo_channels"):
        first = hook.receive(body, header)
        replay = hook.receive(body, header)
    assert first.status == 200
    assert [o.result for o in first.outcomes] == ["failed"]
    assert replay.status == 200
    assert [o.result for o in replay.outcomes] == ["duplicate"]
    assert calls == [wamid(1)], "a failed message is never retried: the claim is kept"
    logged = caplog.text
    assert SECRET_TEXT not in logged and NUMBER_A not in logged and secret.decode() not in logged
    assert "failed" in logged
