"""FR-CHN-17f, security review 7b B2: the real ID-token check of `POST /internal/push/send` is bounded.

The route is public, so a token is refused from its own header and claims before any certificate fetch (junk and wrong
audience cost zero fetches), the fetch has a short timeout, certificates are cached, an unknown key id fetches at most
once inside the cooldown, a correctly signed token for the audience is accepted, and the check runs off the event loop.
Tokens are signed with a throwaway RSA key made at run time; the transport is a counting fake (nothing leaves the
process)."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
from tilo_channels import push_verifier
from tilo_channels.app import app
from tilo_channels.push_routes import ENV_AUDIENCE, ENV_CALLER, get_sender, get_verifier
from tilo_channels.push_verifier import GoogleOidcVerifier

AUD, CALLER = "https://tilo-channels-abc123.a.run.app", "tilo-api@proj.iam.gserviceaccount.com"
ISSUER, KID = "https://accounts.google.com", "kid-one"
BODY = {
    "devices": [{"endpoint": "https://fcm.googleapis.com/fcm/send/" + "a" * 40, "keys": {"p256dh": "B", "auth": "y"}}],
    "title": "A send is waiting for your approval",
    "body": "",
    "tag": "gate-card_1",
    "path": "/park/home?card=card_1",
}


@pytest.fixture(scope="module")
def keypair() -> tuple[bytes, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tilo-test")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return private, cert.public_bytes(serialization.Encoding.PEM).decode()


def _token(private: bytes, *, kid: str = KID, **claims: Any) -> str:
    now = int(time.time())
    payload = {"iss": ISSUER, "aud": AUD, "email": CALLER, "email_verified": True, "iat": now, "exp": now + 3600}
    payload.update(claims)
    signer = crypt.RSASigner.from_string(private, key_id=kid)
    return jwt.encode(signer, payload, header={"kid": kid}).decode()


def _b64(obj: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


class Transport:
    """google-auth's `Request` shape; counts every certificate request with the timeout it carried."""

    def __init__(self, certs: dict[str, str]) -> None:
        self.certs, self.calls = certs, []

    def __call__(self, url: str, method: str = "GET", timeout: float = 120, **kwargs: Any) -> Any:
        self.calls.append({"url": url, "timeout": timeout})

        class _Response:
            status, data = 200, json.dumps(self.certs).encode()

        return _Response()


class Clock:
    now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def rig(keypair: tuple[bytes, str]):
    private, cert = keypair
    transport, clock = Transport({KID: cert}), Clock()
    return private, transport, clock, GoogleOidcVerifier(transport=transport, clock=clock)


def _junk(private: bytes) -> list[str]:
    hs256 = f"{_b64({'alg': 'HS256', 'kid': KID})}.{_b64({'iss': ISSUER, 'aud': AUD})}.sig"
    no_kid = f"{_b64({'alg': 'RS256'})}.{_b64({'iss': ISSUER, 'aud': AUD})}.sig"
    return [
        "junk",
        "a.b.c",
        "x" * 9000,
        hs256,
        no_kid,
        _token(private, aud="https://other.a.run.app"),  # valid shape, signed, wrong audience
        _token(private, iss="https://evil.example"),
    ] * 3  # 21 tokens


def test_FR_CHN_17f_junk_and_wrong_audience_tokens_cause_zero_certificate_fetches(rig) -> None:
    private, transport, _, verifier = rig
    for token in _junk(private):
        with pytest.raises(ValueError):
            verifier.verify(token, AUD)
    assert transport.calls == []


def test_FR_CHN_17f_a_correctly_signed_token_is_accepted_with_one_bounded_cached_fetch(rig) -> None:
    private, transport, clock, verifier = rig
    token = _token(private)
    assert verifier.verify(token, AUD)["email"] == CALLER
    assert verifier.verify(token, AUD)["email"] == CALLER  # the second call reads the cache
    assert [c["url"] for c in transport.calls] == [push_verifier.CERT_URL]
    assert transport.calls[0]["timeout"] <= 5
    clock.now += push_verifier.CERT_TTL_S + 1  # past the TTL a second fetch is due
    assert verifier.verify(token, AUD)
    assert len(transport.calls) == 2


def test_FR_CHN_17f_a_signature_from_another_key_is_refused(rig) -> None:
    private, transport, _, verifier = rig
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    with pytest.raises(ValueError):
        verifier.verify(_token(other), AUD)  # right kid and claims, signed by a key Google never published


def test_FR_CHN_17f_an_unknown_key_id_fetches_at_most_once_inside_the_cooldown(rig) -> None:
    private, transport, _, verifier = rig
    for n in range(10):
        with pytest.raises(ValueError):
            verifier.verify(_token(private, kid=f"unknown-{n}"), AUD)
    assert len(transport.calls) <= 1


def test_FR_CHN_17f_the_route_answers_401_for_junk_without_a_fetch_and_checks_off_the_event_loop(
    rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    private, transport, _, verifier = rig
    monkeypatch.setenv(ENV_AUDIENCE, AUD)
    monkeypatch.setenv(ENV_CALLER, CALLER)
    on_loop: list[bool] = []
    real_verify = verifier.verify

    def spy(token: str, audience: str) -> Any:
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)
        return real_verify(token, audience)

    verifier.verify = spy  # type: ignore[method-assign]
    app.dependency_overrides[get_verifier] = lambda: verifier
    app.dependency_overrides[get_sender] = lambda: None
    try:
        client = TestClient(app, raise_server_exceptions=False)
        statuses = {
            client.post("/internal/push/send", json=BODY, headers={"authorization": f"Bearer {t}"}).status_code
            for t in _junk(private)
        }
        assert statuses == {401} and transport.calls == []
        good = client.post("/internal/push/send", json=BODY, headers={"authorization": f"Bearer {_token(private)}"})
        assert good.status_code == 503  # the caller is proven; the fake sender is not configured
        assert len(transport.calls) == 1 and on_loop and not any(on_loop)
    finally:
        app.dependency_overrides.clear()


def test_FR_CHN_17f_the_default_verifier_is_one_shared_instance() -> None:
    assert get_verifier() is get_verifier()
