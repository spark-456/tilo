"""FR-CHN-17b: the production push sender is built only on Cloud Run with a mounted VAPID secret; fakes stay default."""

from __future__ import annotations

import logging
import secrets
from typing import Any

import pytest
from tilo_channels import web_push
from tilo_channels.web_push_sender import (
    ENV_SUBJECT,
    VapidSender,
    production_sender,
    secret_env_name,
)

SUB = web_push.PushSubscription("https://fcm.googleapis.com/fcm/send/" + "a" * 40, "B" + "x" * 86, "y" * 22)
VAPID = web_push.VapidRef("webpush-vapid-private-key")


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _Boom(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(f"push failed for {SUB.endpoint}")
        self.response = None if status is None else _Resp(status)


def _env(**over: str) -> dict[str, str]:
    key = secret_env_name("webpush-vapid-private-key")
    base = {"K_SERVICE": "tilo-channels", ENV_SUBJECT: "mailto:ops@example.com", key: "k" + secrets.token_hex(8)}
    return {**base, **over}


def test_FR_CHN_17b_sender_is_built_only_on_cloud_run_with_the_mounted_secret_and_a_subject() -> None:
    assert secret_env_name("webpush-vapid-private-key") == "WEBPUSH_VAPID_PRIVATE_KEY"
    assert isinstance(production_sender(_env()), VapidSender)
    key = secret_env_name("webpush-vapid-private-key")
    no_cloud = {k: v for k, v in _env().items() if k != "K_SERVICE"}
    no_key = {k: v for k, v in _env().items() if k != key}
    no_subject = {k: v for k, v in _env().items() if k != ENV_SUBJECT}
    for env in (no_cloud, no_key, no_subject, _env(**{ENV_SUBJECT: "not a subject"}), _env(**{key: ""}), {}):
        assert production_sender(env) is None, env
    with pytest.raises(ValueError):
        secret_env_name("Not A Secret Name")


def test_FR_CHN_17b_send_signs_with_the_mounted_key_once_and_maps_refusals_without_leaking(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[dict[str, Any]] = []
    key_value = "k" + secrets.token_hex(8)
    outcomes: list[Exception | None] = [None, _Boom(410), _Boom(404), _Boom(500), _Boom(None)]

    def push(**kw: Any) -> None:
        calls.append(kw)
        if (out := outcomes.pop(0)) is not None:
            raise out

    sender = VapidSender(
        read_key=lambda name: key_value, subject="mailto:ops@example.com", push=push, parse_key=lambda k: k
    )
    with caplog.at_level(logging.DEBUG):
        sender.send(SUB, b'{"title":"x"}', VAPID)
        for expected in (web_push.SubscriptionGone, web_push.SubscriptionGone, web_push.PushUndelivered):
            with pytest.raises(expected) as raised:
                sender.send(SUB, b"{}", VAPID)
            assert SUB.endpoint not in str(raised.value) and key_value not in str(raised.value)
            assert raised.value.__cause__ is None and raised.value.__suppress_context__
        with pytest.raises(web_push.PushUndelivered):
            sender.send(SUB, b"{}", VAPID)  # no response at all: network failure
    assert calls[0]["subscription_info"]["endpoint"] == SUB.endpoint
    assert calls[0]["vapid_claims"] == {"sub": "mailto:ops@example.com"}
    assert calls[0]["timeout"] <= web_push.load_config().send_within_s and calls[0]["ttl"] == 3600
    assert key_value not in " ".join(r.getMessage() for r in caplog.records)
    missing = VapidSender(read_key=lambda name: None, subject="mailto:ops@example.com", push=push)
    with pytest.raises(web_push.PushUndelivered):
        missing.send(SUB, b"{}", VAPID)
    assert len(calls) == 5  # the missing key never reached the push service
