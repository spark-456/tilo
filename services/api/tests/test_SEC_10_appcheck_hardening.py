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


def test_SEC_10_keys_past_their_ttl_and_their_grace_are_never_served_when_the_refresh_fails(signer):
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
    verifier.verify(
        _token(signer)
    )  # past the TTL: a refresh is tried and fails; the known key still serves in the grace
    assert calls["n"] == 2
    clock.now = appcheck.JWKS_TTL_S + appcheck.JWKS_STALE_GRACE_S + 1
    with pytest.raises(OSError):
        verifier.verify(_token(signer))  # beyond the grace: a refresh is tried, fails, and nothing is served
    clock.now += appcheck.JWKS_RETRY_COOLDOWN_S + 1
    with pytest.raises(OSError):
        verifier.verify(_token(signer))  # the stale keys are gone, not served as a fallback
    assert calls["n"] == 4


def test_SEC_10_the_stale_grace_is_at_most_one_hour():
    assert appcheck.JWKS_STALE_GRACE_S <= 3600.0


def test_SEC_10_a_valid_token_is_served_from_a_stale_snapshot_while_a_refresh_is_in_flight(signer):
    started, release = threading.Event(), threading.Event()
    calls = {"n": 0}

    def fetch() -> dict[str, rsa.RSAPublicKey]:
        calls["n"] += 1
        if calls["n"] == 2:
            started.set()
            release.wait(5)
        return {"k1": signer.public_key()}

    clock = Clock()
    verifier = _verifier(fetch, clock)
    verifier.verify(_token(signer))  # snapshot at t=0
    clock.now = appcheck.JWKS_TTL_S + 5  # past the TTL: the next caller refreshes
    refresher = threading.Thread(target=lambda: verifier.verify(_token(signer)))
    refresher.start()
    assert started.wait(5)
    clock.now += appcheck.JWKS_RETRY_COOLDOWN_S + 1  # past the cooldown: only the in-flight guard is left
    assert verifier.verify(_token(signer))["sub"]  # a second valid token meanwhile: served, not refused
    assert calls["n"] == 2, "no second fetch starts: the single-flight guard stays"
    release.set()
    refresher.join(5)


def test_SEC_10_the_stale_grace_serves_only_a_key_id_it_holds_and_never_past_one_hour(signer):
    started, release = threading.Event(), threading.Event()
    calls = {"n": 0}

    def fetch() -> dict[str, rsa.RSAPublicKey]:
        calls["n"] += 1
        if calls["n"] == 2:
            started.set()
            release.wait(5)
        return {"k1": signer.public_key()}

    clock = Clock()
    verifier = _verifier(fetch, clock)
    verifier.verify(_token(signer))
    clock.now = appcheck.JWKS_TTL_S + 5
    refresher = threading.Thread(target=lambda: verifier.verify(_token(signer)))
    refresher.start()
    assert started.wait(5)
    with pytest.raises(appcheck.TokenRefused) as unknown:
        verifier.verify(_token(signer, kid="never_seen"))
    assert unknown.value.code in {
        "key_refresh_in_flight",
        "keys_unavailable",
        "unknown_key",
    }  # an unknown key id is never guessed at
    clock.now = appcheck.JWKS_TTL_S + appcheck.JWKS_STALE_GRACE_S + 5
    with pytest.raises(appcheck.TokenRefused) as old:
        verifier.verify(_token(signer))
    assert old.value.code in {
        "key_refresh_in_flight",
        "keys_unavailable",
    }  # one hour past the TTL nothing is served from the snapshot
    release.set()
    refresher.join(5)


def test_SEC_10_a_cold_start_with_nothing_held_still_refuses_while_the_first_fetch_runs(signer):
    started, release = threading.Event(), threading.Event()

    def fetch() -> dict[str, rsa.RSAPublicKey]:
        started.set()
        release.wait(5)
        return {"k1": signer.public_key()}

    verifier = _verifier(fetch)
    first = threading.Thread(target=lambda: verifier.verify(_token(signer)))
    first.start()
    assert started.wait(5)
    with pytest.raises(appcheck.TokenRefused) as refused:
        verifier.verify(_token(signer))
    assert refused.value.code in {"key_refresh_in_flight", "keys_unavailable"}  # no snapshot exists to serve from
    release.set()
    first.join(5)


def test_SEC_10_a_well_formed_signed_token_over_the_size_cap_is_refused_before_any_key_fetch(signer):
    fetches: list[int] = []
    verifier = _verifier(lambda: fetches.append(1) or {"k1": signer.public_key()})
    # Every other check passes: header, claims, issuer, audience and a genuine signature. Only the length is wrong.
    token = _token(signer, padding="x" * appcheck.MAX_TOKEN_CHARS)
    assert len(token) > appcheck.MAX_TOKEN_CHARS and token.count(".") == 2
    with pytest.raises(appcheck.TokenRefused) as refused:
        verifier.verify(token)
    assert refused.value.code == "not_a_jwt"
    assert fetches == []
    assert _verifier(lambda: {"k1": signer.public_key()}).verify(_token(signer, padding="x" * 100))["sub"]  # control


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


# --- the warm-up (SEC-SWEEP-1): min-instances 0 makes a true cold start after every idle period ---------


def test_SEC_10_a_warmed_cold_start_serves_the_first_caller(signer):
    verifier = _verifier(lambda: {"k1": signer.public_key()})
    assert verifier.warm() is True
    assert verifier.verify(_token(signer))["sub"]  # the first request after the start needs no fetch of its own


def test_SEC_10_without_the_warm_up_the_first_concurrent_callers_meet_the_fetch(signer):
    started, release = threading.Event(), threading.Event()

    def fetch() -> dict[str, rsa.RSAPublicKey]:
        started.set()
        release.wait(5)
        return {"k1": signer.public_key()}

    verifier = _verifier(fetch)
    first = threading.Thread(target=lambda: verifier.verify(_token(signer)))
    first.start()
    assert started.wait(5)
    with pytest.raises(appcheck.TokenRefused):
        verifier.verify(_token(signer))  # the case the warm-up removes
    release.set()
    first.join(5)


def test_SEC_10_a_failed_warm_up_is_quiet_and_changes_nothing(signer):
    def fetch() -> dict[str, rsa.RSAPublicKey]:
        raise OSError("keys endpoint down")

    verifier = _verifier(fetch)
    assert verifier.warm() is False  # best effort: no exception, nothing stored
    with pytest.raises(OSError):
        verifier.verify(_token(signer))  # nothing was stored: a later request tries for itself


def test_SEC_10_warming_a_warm_cache_fetches_nothing(signer):
    calls = {"n": 0}

    def fetch() -> dict[str, rsa.RSAPublicKey]:
        calls["n"] += 1
        return {"k1": signer.public_key()}

    verifier = _verifier(fetch)
    assert verifier.warm() and verifier.warm()
    assert calls["n"] == 1


def test_SEC_10_the_app_start_warms_both_verifiers_and_never_blocks_on_failure(monkeypatch):
    from tilo_api import firebase_auth

    warmed: list[str] = []

    class Quiet:
        def __init__(self, name: str, ok: bool) -> None:
            self.name, self.ok = name, ok

        def warm(self) -> bool:
            warmed.append(self.name)
            if not self.ok:
                raise RuntimeError("boom")  # even a surprise must not reach the start
            return True

    monkeypatch.setattr(appcheck, "default_verifier", lambda: Quiet("appcheck", False))
    monkeypatch.setattr(firebase_auth, "default_verifier", lambda: Quiet("firebase", True))
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    appcheck.warm_up()
    assert sorted(warmed) == ["appcheck", "firebase"]


def test_SEC_10_the_refusing_verifiers_have_nothing_to_warm():
    appcheck.RefuseAll("dev_mode").warm()  # dev mode and an unconfigured project open no socket


def test_SEC_10_outside_cloud_run_the_warm_up_opens_no_socket(monkeypatch):
    from tilo_api import firebase_auth

    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.setattr(appcheck, "default_verifier", lambda: pytest.fail("a laptop or CI never warms"))
    monkeypatch.setattr(firebase_auth, "default_verifier", lambda: pytest.fail("a laptop or CI never warms"))
    appcheck.warm_up()


def test_SEC_10_the_app_start_runs_the_warm_up_in_the_background(monkeypatch):
    import tilo_api
    from fastapi.testclient import TestClient

    ran = threading.Event()
    monkeypatch.setattr(appcheck, "warm_up", ran.set)
    with TestClient(tilo_api.app):
        assert ran.wait(5)
