"""SEC-10 (PR-2 follow-ups of the PR-1 review): the exempt list is pinned, enforcement closes the public access routes
and a POST, the verifier's surviving mutants are killed (key TTL, token size cap, single-flight refresh, audience
match), and every refusal logs a fixed reason code, never the token.

No network, no secret: keys are made at runtime and the key fetch is injected."""

from __future__ import annotations

import base64
import json
import logging
import threading

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from tilo_api import app as tilo_app
from tilo_api import appcheck, deps

PROJECT = "demo-tilo"
NOW = 1_800_000_000.0
HEADER = "X-Firebase-AppCheck"
ENFORCE = "TILO_APPCHECK_ENFORCE"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def signer() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key: rsa.RSAPrivateKey, *, kid: str = "k1", **claims: object) -> str:
    body = {
        "iss": appcheck.ISSUER_PREFIX + "123",
        "aud": ["projects/123", f"projects/{PROJECT}"],
        "sub": "1:123:web:abc",
        "exp": NOW + 600,
        **claims,
    }
    signing = _b64(json.dumps({"alg": "RS256", "kid": kid}).encode()) + "." + _b64(json.dumps(body).encode())
    return signing + "." + _b64(key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256()))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _verifier(fetch, clock: Clock | None = None) -> appcheck.GoogleAppCheckVerifier:
    return appcheck.GoogleAppCheckVerifier(PROJECT, fetch=fetch, clock=clock or Clock(), wall=lambda: NOW)


# --- the exempt list and enforcement on the public and write routes ---------------------------------


def test_SEC_10_exempt_routes_are_exactly_the_three_pairs():
    assert appcheck.EXEMPT_ROUTES == {("GET", "/health"), ("GET", "/healthz"), ("POST", "/internal/schedules/tick")}


def test_SEC_10_on_the_public_access_route_and_a_post_route_are_401_without_a_token(client, monkeypatch):
    class Refuses:
        def verify(self, token: str):
            raise appcheck.TokenRefused("expired")

    monkeypatch.setenv(ENFORCE, "1")
    tilo_app.dependency_overrides[deps.get_app_check_verifier] = lambda: Refuses()
    for method, path in (("GET", "/access"), ("POST", "/access/declaration"), ("POST", "/worlds/w_none/pause")):
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 401, (method, path, response.status_code)
        assert response.json()["code"] == "app_check_required"
        assert client.request(method, path, headers={HEADER: "a.b.c"}).status_code == 401, (method, path)


# --- reasons are logged as fixed codes, never the token ---------------------------------------------


def _gate_log(client, monkeypatch, caplog, verifier, token: str) -> str:
    monkeypatch.delenv(ENFORCE, raising=False)
    tilo_app.dependency_overrides[deps.get_app_check_verifier] = lambda: verifier
    with caplog.at_level(logging.DEBUG, logger="tilo_api.appcheck"):
        assert client.get("/worlds", headers={HEADER: token} if token else {}).status_code == 200
    return caplog.text


def test_SEC_10_a_refused_token_logs_its_fixed_reason_code_and_never_the_token(client, monkeypatch, caplog):
    class Refuses:
        def verify(self, token: str):
            raise appcheck.TokenRefused("bad_signature")

    secretish = "fake.appcheck.refused.x9"
    text = _gate_log(client, monkeypatch, caplog, Refuses(), secretish)
    assert "reason=bad_signature" in text
    assert secretish not in text


def test_SEC_10_a_failing_verifier_logs_only_its_error_type(client, monkeypatch, caplog):
    class Breaks:
        def verify(self, token: str):
            raise OSError("host 10.0.0.1 unreachable")

    text = _gate_log(client, monkeypatch, caplog, Breaks(), "fake.appcheck.valid.x1")
    assert "reason=verifier_failed:OSError" in text
    assert "10.0.0.1" not in text


def test_SEC_10_a_missing_token_logs_the_reason_missing(client, monkeypatch, caplog):
    text = _gate_log(client, monkeypatch, caplog, appcheck.default_verifier(), "")
    assert "reason=missing" in text


@pytest.mark.parametrize(
    ("claims", "code"),
    [
        ({"aud": ["projects/other"]}, "wrong_project"),
        ({"iss": "https://example.test/1"}, "wrong_issuer"),
        ({"sub": ""}, "no_app"),
        ({"exp": NOW - 60}, "expired"),
        ({"nbf": NOW + 600}, "not_yet_valid"),
    ],
)
def test_SEC_10_the_verifier_names_each_claim_refusal(signer, claims, code):
    verifier = _verifier(lambda: {"k1": signer.public_key()})
    with pytest.raises(appcheck.TokenRefused) as refused:
        verifier.verify(_token(signer, **claims))
    assert refused.value.code == code


def test_SEC_10_the_verifier_names_the_other_refusals(signer):
    verifier = _verifier(lambda: {"k1": signer.public_key()})
    for token, code in (("a.b", "not_a_jwt"), ("e30.e30.e30", "not_an_app_check_token")):
        with pytest.raises(appcheck.TokenRefused) as refused:
            verifier.verify(token)
        assert refused.value.code == code
    with pytest.raises(appcheck.TokenRefused) as unknown:
        verifier.verify(_token(signer, kid="nope"))
    assert unknown.value.code == "unknown_key"
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(appcheck.TokenRefused) as bad:
        verifier.verify(_token(other))
    assert bad.value.code == "bad_signature"


# --- mutants the PR-1 review found alive -------------------------------------------------------------


def test_SEC_10_keys_past_their_ttl_are_never_served_when_the_refresh_fails(signer):
    calls = {"n": 0}

    def fetch() -> dict[str, rsa.RSAPublicKey]:
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("down")
        return {"k1": signer.public_key()}

    clock = Clock()
    verifier = _verifier(fetch, clock)
    verifier.verify(_token(signer))  # fetched at t=0
    clock.now = appcheck.JWKS_TTL_S - 1
    verifier.verify(_token(signer))  # still inside the TTL: served from the snapshot
    assert calls["n"] == 1
    clock.now = appcheck.JWKS_TTL_S + 1
    with pytest.raises(OSError):
        verifier.verify(_token(signer))  # past the TTL: a refresh is tried, and it fails
    clock.now = appcheck.JWKS_TTL_S + 1 + appcheck.JWKS_RETRY_COOLDOWN_S + 1
    with pytest.raises(OSError):
        verifier.verify(_token(signer))  # the stale keys are gone, not served as a fallback
    assert calls["n"] == 3


def test_SEC_10_a_three_part_token_over_the_size_cap_is_refused_before_any_key_fetch():
    fetches: list[int] = []
    verifier = _verifier(lambda: fetches.append(1) or {})
    body = "a" * (appcheck.MAX_TOKEN_CHARS // 2)
    token = f"{body}.{body}.sig"
    assert len(token) > appcheck.MAX_TOKEN_CHARS and token.count(".") == 2
    with pytest.raises(appcheck.TokenRefused) as refused:
        verifier.verify(token)
    assert refused.value.code == "not_a_jwt"
    assert fetches == []


def test_SEC_10_a_genuine_token_at_the_size_cap_boundary_is_judged_on_its_content(signer):
    verifier = _verifier(lambda: {"k1": signer.public_key()})
    small = _token(signer)
    assert len(small) < appcheck.MAX_TOKEN_CHARS
    assert verifier.verify(small)["sub"] == "1:123:web:abc"


def test_SEC_10_only_one_key_fetch_is_in_flight_and_a_second_caller_is_refused_at_once(signer):
    started, release = threading.Event(), threading.Event()
    calls = {"n": 0}

    def fetch() -> dict[str, rsa.RSAPublicKey]:
        calls["n"] += 1
        started.set()
        assert release.wait(10), "the test never released the fetch"
        return {"k1": signer.public_key()}

    clock = Clock()
    verifier = _verifier(fetch, clock)
    results: list[object] = []

    def first() -> None:
        results.append(verifier.verify(_token(signer))["sub"])

    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert started.wait(10)
        clock.now = appcheck.JWKS_RETRY_COOLDOWN_S + 1  # past the cooldown, so only the lock stops a second fetch
        with pytest.raises(appcheck.TokenRefused) as refused:  # a second caller while the fetch is running
            verifier.verify(_token(signer))
        assert refused.value.code == "key_refresh_in_flight"
        assert calls["n"] == 1
    finally:
        release.set()
        thread.join(10)
    assert results == ["1:123:web:abc"]
    assert calls["n"] == 1


@pytest.mark.parametrize(
    "audience",
    [
        f"projects/{PROJECT}x",  # a prefix match would let it in
        [f"projects/{PROJECT}x"],
        [f"xprojects/{PROJECT}", "projects/123"],  # a suffix match would let it in
        f"projects/{PROJECT}-extra",
        PROJECT,  # the bare id is not the audience either
    ],
)
def test_SEC_10_the_audience_must_equal_projects_slash_the_project(signer, audience):
    verifier = _verifier(lambda: {"k1": signer.public_key()})
    with pytest.raises(appcheck.TokenRefused) as refused:
        verifier.verify(_token(signer, aud=audience))
    assert refused.value.code == "wrong_project"
