"""FR-CHN-17f: `POST /internal/push/send`, the one place a web push leaves the platform. The caller is proven first; the
sender is the fake of the tests (the real one exists only on Cloud Run with the mounted secret); the answer holds
counts and positions only."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tilo_channels import web_push
from tilo_channels.app import app
from tilo_channels.push_routes import ENV_AUDIENCE, ENV_CALLER, get_sender, get_verifier

AUD, CALLER = "https://tilo-channels-abc123.a.run.app", "tilo-api@proj.iam.gserviceaccount.com"
FCM = "https://fcm.googleapis.com/fcm/send/" + "a" * 40
KEYS = {"p256dh": "B" + "x" * 86, "auth": "y" * 22}
NOTICE = {
    "title": "A send is waiting for your approval",
    "body": "",
    "tag": "gate-card_1",
    "path": "/park/home?card=card_1",
}
HEADERS = {"authorization": "Bearer id-token"}


class Verifier:
    def __init__(self, claims: dict[str, Any] | Exception) -> None:
        self.claims, self.seen = claims, []

    def verify(self, token: str, audience: str) -> dict[str, Any]:
        self.seen.append((token, audience))
        if isinstance(self.claims, Exception):
            raise self.claims
        return self.claims


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes]] = []
        self.gone: set[str] = set()
        self.fail: set[str] = set()

    def send(self, sub: web_push.PushSubscription, payload: bytes, vapid: web_push.VapidRef) -> None:
        if sub.endpoint in self.gone:
            raise web_push.SubscriptionGone("gone")
        if sub.endpoint in self.fail:
            raise RuntimeError(f"vendor says no about {sub.endpoint}")
        self.sent.append((sub.endpoint, payload))


@pytest.fixture()
def rig(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(ENV_AUDIENCE, AUD)
    monkeypatch.setenv(ENV_CALLER, CALLER)
    verifier = Verifier({"email": CALLER, "email_verified": True, "aud": AUD})
    sender = Sender()
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_sender] = lambda: sender
    yield TestClient(app, raise_server_exceptions=False), verifier, sender
    app.dependency_overrides.clear()


def _body(*endpoints: str, **over: Any) -> dict[str, Any]:
    return (
        {"devices": [{"endpoint": e, "keys": KEYS} for e in endpoints] or [{"endpoint": FCM, "keys": KEYS}]}
        | NOTICE
        | over
    )


def test_FR_CHN_17f_a_verified_caller_gets_every_device_the_fixed_payload_and_counts_only(rig) -> None:
    client, verifier, sender = rig
    other = FCM.replace("a" * 40, "b" * 40)
    res = client.post("/internal/push/send", json=_body(FCM, other), headers=HEADERS)
    assert (res.status_code, res.json()) == (200, {"delivered": 2, "gone": [], "refused": []})
    assert verifier.seen == [("id-token", AUD)] and res.headers["cache-control"] == "no-store"
    assert [e for e, _ in sender.sent] == [FCM, other]
    assert json.loads(sender.sent[0][1]) == NOTICE  # exactly the fixed shape: title, body, tag, path
    assert FCM not in res.text and KEYS["auth"] not in res.text


def test_FR_CHN_17f_gone_failed_and_refused_devices_are_told_by_position_without_vendor_text(rig) -> None:
    client, _, sender = rig
    gone, failed = FCM.replace("a" * 40, "c" * 40), FCM.replace("a" * 40, "d" * 40)
    sender.gone, sender.fail = {gone}, {failed}
    body = _body(FCM, gone, failed, "https://evil.example/x" + "a" * 20)
    res = client.post("/internal/push/send", json=body, headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == {"delivered": 1, "gone": [1], "refused": [3]}
    assert "vendor" not in res.text and failed not in res.text and gone not in res.text


@pytest.mark.parametrize(
    ("headers", "claims", "status"),
    [
        ({}, None, 401),
        ({"authorization": "Basic abc"}, None, 401),
        (HEADERS, RuntimeError("bad signature"), 401),
        (HEADERS, {"email": "someone@else.example", "email_verified": True, "aud": AUD}, 403),
        (HEADERS, {"email": CALLER, "email_verified": False, "aud": AUD}, 403),
        (HEADERS, {"email": CALLER, "email_verified": True, "aud": "https://other.a.run.app"}, 403),
    ],
)
def test_FR_CHN_17f_the_caller_is_proven_before_anything_is_read_or_sent(rig, headers, claims, status) -> None:
    client, verifier, sender = rig
    if claims is not None:
        verifier.claims = claims
    res = client.post("/internal/push/send", json=_body(), headers=headers)
    assert res.status_code == status and sender.sent == []


def test_FR_CHN_17f_unset_audience_caller_or_sender_is_not_configured_and_sends_nothing(
    rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, sender = rig
    app.dependency_overrides[get_sender] = lambda: None
    assert client.post("/internal/push/send", json=_body(), headers=HEADERS).status_code == 503
    app.dependency_overrides[get_sender] = lambda: sender
    for name in (ENV_AUDIENCE, ENV_CALLER):
        monkeypatch.delenv(name)
        assert client.post("/internal/push/send", json=_body(), headers=HEADERS).status_code == 503
        monkeypatch.setenv(name, AUD if name == ENV_AUDIENCE else CALLER)
    assert sender.sent == []


def test_FR_CHN_17f_body_is_json_only_bounded_and_closed(rig) -> None:
    client, _, sender = rig
    post = client.post
    assert (
        post(
            "/internal/push/send", content=json.dumps(_body()), headers={**HEADERS, "content-type": "text/plain"}
        ).status_code
        == 415
    )
    assert post("/internal/push/send", json=_body(pad="x" * 9000), headers=HEADERS).status_code == 413
    assert post("/internal/push/send", json=_body(extra="x"), headers=HEADERS).status_code == 422
    assert post("/internal/push/send", json=_body(path="https://evil.example/x"), headers=HEADERS).status_code == 422
    assert post("/internal/push/send", json=_body(path="/park/world/w_1"), headers=HEADERS).status_code == 422
    assert (
        post("/internal/push/send", json=_body(*[FCM + str(n) for n in range(6)]), headers=HEADERS).status_code == 422
    )
    assert post("/internal/push/send", json=_body(title=""), headers=HEADERS).status_code == 422
    assert sender.sent == []
