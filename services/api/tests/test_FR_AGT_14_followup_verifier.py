"""FR-AGT-14d items 5 and 6 (security review of the infra PR): the tick's Google verifier and what the route logs.

5. The default verifier (`tilo_api.schedules.GoogleOidcVerifier`) fetched Google's public certificates on every call,
   through google-auth's default transport (120 s timeout), with no cache: a slow or hung certificate endpoint held a
   request thread for two minutes and every call paid a round trip. Pinned here, with a counting fake transport and a
   fake clock (real RS256 tokens signed with a throwaway key made at run time; nothing leaves the process):
   (a) the certificate request carries a timeout of at most `CERT_FETCH_TIMEOUT_S` (<= 5 s);
   (b) two verifications with the same `kid` within `CERT_TTL_S` (300..3600 s) make ONE fetch, one after the TTL a
       second;
   (c) a failed fetch (an error status, or the transport raising) is not cached as a success and does not poison the
       next call.
   The default dependency returns ONE shared verifier, so the cache lives across requests.
6. When the verifier raises (any error) the route still answers 401 with its fixed body and logs ONE line holding
   `type(exc).__name__` only: never the token, never the exception text, no traceback.

Interface: API_FR_AGT_14d.md (section 5 and 6). Fakes: this file; the rest of the tick matrix is in
test_FR_AGT_14_tick_route.py.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from typing import Any

import pytest
from _fr_agt_14_lib import AUDIENCE, GOOGLE_ISSUER, SCHEDULE_SA, SchedApi, bearer
from google.auth import crypt, jwt

KID = "kid-test-one"


# --- a throwaway signing key and its certificate, made at run time ---------------------------------------------------


@pytest.fixture(scope="module")
def keypair() -> tuple[bytes, str]:
    """(private key PEM, certificate PEM) of a fresh RSA key. Never written anywhere."""
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


def make_token(private: bytes, *, kid: str = KID, **claims: Any) -> str:
    now = int(time.time())
    payload = {
        "iss": GOOGLE_ISSUER, "aud": AUDIENCE, "email": SCHEDULE_SA, "email_verified": True,
        "iat": now, "exp": now + 3600, "sub": "1234567890",
    }  # fmt: skip
    payload.update(claims)
    signer = crypt.RSASigner.from_string(private, key_id=kid)
    return jwt.encode(signer, payload, header={"kid": kid}).decode()


class Response:
    def __init__(self, status: int, data: bytes) -> None:
        self.status, self.data, self.headers = status, data, {}


class CountingTransport:
    """The shape of google.auth.transport.Request: `(url, method="GET", body=None, headers=None, timeout=120, **kw)`.
    The default timeout is google-auth's own 120 s, so a verifier that does not pass one shows up as 120 here."""

    def __init__(self, certs: dict[str, str]) -> None:
        self.certs, self.mode, self.calls = certs, "ok", []

    def __call__(
        self, url: str, method: str = "GET", body: Any = None, headers: Any = None, timeout: float = 120, **kwargs: Any
    ) -> Response:
        self.calls.append({"url": url, "method": method, "timeout": timeout, **kwargs})
        if self.mode == "raise":
            raise OSError("network is down")
        if self.mode == "status500":
            return Response(500, b"")
        return Response(200, json.dumps(self.certs).encode())


class FakeClock:
    """Seconds, monotonic-like: `Callable[[], float]`. Moves only when the test moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Rig:
    def __init__(self, keypair: tuple[bytes, str]) -> None:
        from tilo_api import schedules

        self.private, cert = keypair
        self.transport, self.clock = CountingTransport({KID: cert}), FakeClock()
        self.verifier = schedules.GoogleOidcVerifier(transport=self.transport, clock=self.clock)
        self.ttl = schedules.CERT_TTL_S

    def token(self, **claims: Any) -> str:
        return make_token(self.private, **claims)


@pytest.fixture
def rig(keypair: tuple[bytes, str]) -> Rig:
    return Rig(keypair)


# --- 5. the certificate fetch --------------------------------------------------------------------------------------


def test_FR_AGT_14_the_module_pins_a_short_fetch_timeout_and_a_ttl_between_five_minutes_and_an_hour() -> None:
    from tilo_api import schedules

    assert 0 < schedules.CERT_FETCH_TIMEOUT_S <= 5
    assert 300 <= schedules.CERT_TTL_S <= 3600


def test_FR_AGT_14_the_verifier_checks_a_real_signed_token_through_the_injected_transport(rig: Rig) -> None:
    claims = rig.verifier.verify(rig.token(), AUDIENCE)
    assert claims["email"] == SCHEDULE_SA and claims["aud"] == AUDIENCE and claims["iss"] == GOOGLE_ISSUER
    assert len(rig.transport.calls) == 1 and rig.transport.calls[0]["method"] == "GET"
    assert rig.transport.calls[0]["url"].startswith("https://www.googleapis.com/")


def test_FR_AGT_14_the_certificate_request_has_a_timeout_of_at_most_five_seconds(rig: Rig) -> None:
    from tilo_api import schedules

    rig.verifier.verify(rig.token(), AUDIENCE)
    (call,) = rig.transport.calls
    assert call["timeout"] is not None and 0 < call["timeout"] <= 5, call
    assert call["timeout"] <= schedules.CERT_FETCH_TIMEOUT_S


def test_FR_AGT_14_two_verifications_with_the_same_kid_within_the_ttl_fetch_the_certificates_once(rig: Rig) -> None:
    for _ in range(3):
        rig.verifier.verify(rig.token(), AUDIENCE)
    rig.clock.now += rig.ttl - 1
    rig.verifier.verify(rig.token(), AUDIENCE)
    assert len(rig.transport.calls) == 1


def test_FR_AGT_14_after_the_ttl_the_certificates_are_fetched_again_once(rig: Rig) -> None:
    rig.verifier.verify(rig.token(), AUDIENCE)
    rig.clock.now += rig.ttl + 1
    rig.verifier.verify(rig.token(), AUDIENCE)
    rig.verifier.verify(rig.token(), AUDIENCE)
    assert len(rig.transport.calls) == 2


def test_FR_AGT_14_the_cache_is_timed_from_the_fetch_not_from_the_last_use(rig: Rig) -> None:
    rig.verifier.verify(rig.token(), AUDIENCE)
    for _ in range(4):  # a steady stream of calls must not keep a stale certificate set alive for ever
        rig.clock.now += rig.ttl * 0.4
        rig.verifier.verify(rig.token(), AUDIENCE)
    assert len(rig.transport.calls) == 2


@pytest.mark.parametrize("mode", ["status500", "raise"])
def test_FR_AGT_14_a_failed_fetch_is_not_cached_and_does_not_poison_the_next_call(rig: Rig, mode: str) -> None:
    rig.transport.mode = mode
    for _ in range(2):  # a failure is a failure every time, and each retry may try the endpoint again
        with pytest.raises(Exception):  # noqa: B017, PT011 - any error type: the route turns all of them into 401
            rig.verifier.verify(rig.token(), AUDIENCE)
    failed = len(rig.transport.calls)
    assert failed >= 1
    rig.transport.mode = "ok"
    assert rig.verifier.verify(rig.token(), AUDIENCE)["email"] == SCHEDULE_SA  # the next call just works
    assert len(rig.transport.calls) == failed + 1
    rig.verifier.verify(rig.token(), AUDIENCE)
    assert len(rig.transport.calls) == failed + 1  # and the success IS cached


def test_FR_AGT_14_a_forged_signature_is_refused_and_leaves_the_cache_usable(rig: Rig) -> None:
    other = _other_private_key()
    with pytest.raises(Exception):  # noqa: B017, PT011
        rig.verifier.verify(make_token(other), AUDIENCE)
    assert rig.verifier.verify(rig.token(), AUDIENCE)["email"] == SCHEDULE_SA
    assert len(rig.transport.calls) == 1


def _other_private_key() -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


@pytest.mark.parametrize(
    "claims",
    [{"iss": "https://evil.example.com"}, {"aud": "https://other.example.com"}],
    ids=["not a Google issuer", "not our audience"],
)
def test_FR_AGT_14_a_token_that_is_plainly_not_ours_is_refused_before_any_fetch(
    rig: Rig, claims: dict[str, Any]
) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011
        rig.verifier.verify(rig.token(**claims), AUDIENCE)
    assert rig.transport.calls == []


def test_FR_AGT_14_the_default_dependency_returns_one_shared_verifier_so_the_cache_survives_requests() -> None:
    from tilo_api import schedules

    first, second = schedules.get_oidc_verifier(), schedules.get_oidc_verifier()
    assert first is second and isinstance(first, schedules.GoogleOidcVerifier)


# --- 6. what the route logs when the verifier raises -----------------------------------------------------------------


@pytest.fixture
def sched(clear_flow, monkeypatch) -> SchedApi:
    return SchedApi(clear_flow, monkeypatch)


class SecretError(Exception):
    pass


@pytest.mark.parametrize("exc_type", [RuntimeError, ValueError, OSError, SecretError, KeyError])
def test_FR_AGT_14_a_raising_verifier_is_401_and_logs_one_line_with_the_type_name_only(
    sched: SchedApi, caplog: pytest.LogCaptureFixture, exc_type: type[Exception]
) -> None:
    from tilo_api import schedules

    token = "tok-" + "Zq9xK2mP7vL4nR8s"
    message = "certificate endpoint said: password hunter2 for alice@example.com and " + token

    class Raising:
        def verify(self, token: str, audience: str) -> Any:
            raise exc_type(message)

    sched.app.dependency_overrides[schedules.get_oidc_verifier] = lambda: Raising()
    caplog.set_level(logging.DEBUG)
    response = sched.tick(headers=bearer(token))
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"
    mine = [r for r in caplog.records if r.name == "tilo_api.schedules"]
    assert len(mine) == 1, [r.getMessage() for r in mine]
    (record,) = mine
    assert exc_type.__name__ in record.getMessage()
    assert record.exc_info is None and record.exc_text is None  # no traceback, which would carry the message
    for secret in (token, "hunter2", "alice@example.com", "certificate endpoint said", "Zq9xK2mP7vL4nR8s"):
        assert secret not in caplog.text, secret
        assert secret not in response.text


def test_FR_AGT_14_a_token_with_no_verifier_error_logs_nothing_about_the_verifier(
    sched: SchedApi, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    assert sched.tick().status_code == 200
    assert [r for r in caplog.records if r.name == "tilo_api.schedules" and r.levelno >= logging.WARNING] == []
