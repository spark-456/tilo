"""FR-CHN-17c: the production push sender is built only on Cloud Run with a mounted VAPID secret; fakes stay default;
every request is re-checked, bounded and answers with static messages (SEC-REVIEW-7)."""

from __future__ import annotations

import logging
import secrets
from typing import Any

import pytest
from tilo_channels import web_push
from tilo_channels.web_push_sender import (
    CLAIM_EXP_S,
    ENV_SUBJECT,
    TIMEOUT_S,
    VapidSender,
    _plain_session,
    production_sender,
    secret_env_name,
)

SUB = web_push.PushSubscription("https://fcm.googleapis.com/fcm/send/" + "a" * 40, "B" + "x" * 86, "y" * 22)
VAPID = web_push.VapidRef("webpush-vapid-private-key")
SUBJECT = "mailto:ops@example.com"
NOW = 1_800_000_000.0


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _Boom(Exception):
    def __init__(self, status: int | None) -> None:
        super().__init__(f"push failed for {SUB.endpoint}")
        self.response = None if status is None else _Resp(status)


def _env(**over: str) -> dict[str, str]:
    key = secret_env_name("webpush-vapid-private-key")
    base = {"K_SERVICE": "tilo-channels", ENV_SUBJECT: SUBJECT, key: "k" + secrets.token_hex(8)}
    return {**base, **over}


def _sender(push: Any, key: str | None = "k" + "0" * 16, **over: Any) -> VapidSender:
    kwargs: dict[str, Any] = {
        "read_key": lambda name: key,
        "subject": SUBJECT,
        "push": push,
        "parse_key": lambda k: k,
        "resolves_public": lambda host: True,
        "now": lambda: NOW,
    }
    return VapidSender(**(kwargs | over))


def test_FR_CHN_17c_sender_is_built_only_on_cloud_run_with_the_mounted_secret_and_a_subject() -> None:
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


def test_FR_CHN_17c_claims_have_the_endpoint_origin_a_short_exp_and_the_tilo_contact() -> None:
    calls: list[dict[str, Any]] = []
    _sender(lambda **kw: calls.append(kw)).send(SUB, b'{"title":"x"}', VAPID)
    (call,) = calls
    assert call["vapid_claims"] == {"sub": SUBJECT, "aud": "https://fcm.googleapis.com", "exp": int(NOW) + CLAIM_EXP_S}
    assert CLAIM_EXP_S <= 300 and call["ttl"] == 3600
    assert call["timeout"] == TIMEOUT_S and sum(TIMEOUT_S) < web_push.load_config().send_within_s
    assert call["subscription_info"]["endpoint"] == SUB.endpoint
    with pytest.raises(ValueError):  # a timeout that would not fit the bound refuses to build
        import tilo_channels.web_push_sender as mod

        original = mod.TIMEOUT_S
        mod.TIMEOUT_S = (6, 6)
        try:
            _sender(lambda **kw: None)
        finally:
            mod.TIMEOUT_S = original


def test_FR_CHN_17c_host_and_resolved_addresses_are_checked_again_right_before_the_request() -> None:
    calls: list[dict[str, Any]] = []
    evil = web_push.PushSubscription("https://evil.example/x/" + "a" * 20, SUB.p256dh, SUB.auth)
    with pytest.raises(web_push.PushUndelivered):
        _sender(lambda **kw: calls.append(kw)).send(evil, b"{}", VAPID)  # not an allowed push service host
    private = _sender(lambda **kw: calls.append(kw), resolves_public=lambda host: False)
    with pytest.raises(web_push.PushUndelivered):
        private.send(SUB, b"{}", VAPID)  # an allowed name that resolves to a non-public address
    assert calls == []  # nothing was sent in either case


def test_FR_CHN_17c_send_maps_refusals_to_static_messages_without_leaking(caplog: pytest.LogCaptureFixture) -> None:
    key_value = "k" + secrets.token_hex(8)
    outcomes: list[Exception | None] = [None, _Boom(410), _Boom(404), _Boom(500), _Boom(429), _Boom(None)]

    def push(**kw: Any) -> None:
        if (out := outcomes.pop(0)) is not None:
            raise out

    sender = _sender(push, key=key_value)
    with caplog.at_level(logging.DEBUG):
        sender.send(SUB, b'{"title":"x"}', VAPID)
        for expected in (
            web_push.SubscriptionGone,
            web_push.SubscriptionGone,
            web_push.PushUndelivered,
            web_push.PushUndelivered,
            web_push.PushUndelivered,
        ):
            with pytest.raises(expected) as raised:
                sender.send(SUB, b"{}", VAPID)
            text = str(raised.value)
            assert SUB.endpoint not in text and key_value not in text and "a" * 20 not in text
            assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert key_value not in " ".join(r.getMessage() for r in caplog.records)
    calls: list[Any] = []
    with pytest.raises(web_push.PushUndelivered):
        _sender(lambda **kw: calls.append(kw), key=None).send(SUB, b"{}", VAPID)
    assert calls == []  # a missing key never reaches the push service


def test_FR_CHN_17c_session_follows_no_redirect_and_reads_no_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _plain_session()
    assert session.trust_env is False and session.max_redirects == 0
    seen: dict[str, Any] = {}

    def fake_send(self: Any, request: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise OSError("no network in tests")

    monkeypatch.setattr("requests.Session.send", fake_send)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    with pytest.raises(OSError):
        session.post("https://fcm.googleapis.com/fcm/send/x", data=b"", timeout=TIMEOUT_S, allow_redirects=True)
    assert seen["allow_redirects"] is False  # even when a caller asks for redirects
    assert not seen.get("proxies")  # the proxy variable was not read
    assert seen["timeout"] == TIMEOUT_S
