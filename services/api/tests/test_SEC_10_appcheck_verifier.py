"""SEC-10: the production App Check verifier (`tilo_api.appcheck.GoogleAppCheckVerifier`), with a key pair made at
runtime and an injected key fetch: no network, no secret in the repo."""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from tilo_api import appcheck

PROJECT = "demo-tilo"
NOW = 1_800_000_000.0


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, *, kid="k1", alg="RS256", **claims) -> str:
    body = {
        "iss": appcheck.ISSUER_PREFIX + "123",
        "aud": ["projects/123", f"projects/{PROJECT}"],
        "sub": "1:123:web:abc",
        "exp": NOW + 600,
        **claims,
    }
    signing = _b64(json.dumps({"alg": alg, "kid": kid}).encode()) + "." + _b64(json.dumps(body).encode())
    signature = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    return signing + "." + _b64(signature)


class Fetch:
    def __init__(self, keys: dict[str, rsa.RSAPublicKey]) -> None:
        self.keys, self.calls = keys, 0

    def __call__(self) -> dict[str, rsa.RSAPublicKey]:
        self.calls += 1
        return self.keys


@pytest.fixture(scope="module")
def signer() -> rsa.RSAPrivateKey:
    return _key()


def _verifier(fetch: Fetch) -> appcheck.GoogleAppCheckVerifier:
    return appcheck.GoogleAppCheckVerifier(PROJECT, fetch=fetch, clock=lambda: 0.0, wall=lambda: NOW)


def test_SEC_10_verifier_accepts_a_genuine_token_and_caches_the_keys(signer):
    fetch = Fetch({"k1": signer.public_key()})
    verifier = _verifier(fetch)
    assert verifier.verify(_token(signer))["sub"] == "1:123:web:abc"
    verifier.verify(_token(signer))
    assert fetch.calls == 1


@pytest.mark.parametrize(
    "claims",
    [{"aud": ["projects/other"]}, {"aud": "projects/other"}, {"exp": NOW - 60}, {"nbf": NOW + 600}, {"sub": ""}]
    + [{"iss": "https://example.test/123"}, {"iss": appcheck.ISSUER_PREFIX}, {"exp": "soon"}],
)
def test_SEC_10_verifier_refuses_a_token_with_wrong_claims(signer, claims):
    verifier = _verifier(Fetch({"k1": signer.public_key()}))
    with pytest.raises(ValueError):
        verifier.verify(_token(signer, **claims))


def test_SEC_10_verifier_refuses_a_token_signed_by_another_key(signer):
    verifier = _verifier(Fetch({"k1": signer.public_key()}))
    with pytest.raises(ValueError):
        verifier.verify(_token(_key()))


@pytest.mark.parametrize("token", ["", "a.b", "a.b.c", "x" * 5000, "e30.e30.e30"])
def test_SEC_10_verifier_refuses_junk_before_any_key_fetch(token):
    fetch = Fetch({})
    with pytest.raises(ValueError):
        _verifier(fetch).verify(token)
    assert fetch.calls == 0


def test_SEC_10_verifier_refuses_alg_none_and_an_unknown_kid_without_a_second_fetch(signer):
    fetch = Fetch({"k1": signer.public_key()})
    verifier = _verifier(fetch)
    with pytest.raises(ValueError):
        verifier.verify(_token(signer, alg="none"))
    assert fetch.calls == 0
    with pytest.raises(ValueError):
        verifier.verify(_token(signer, kid="nope"))
    with pytest.raises(ValueError):
        verifier.verify(_token(signer, kid="nope2"))
    assert fetch.calls == 1  # the second unknown kid is inside the cooldown


def test_SEC_10_a_failed_key_fetch_refuses_the_token_and_is_not_cached(signer):
    def broken() -> dict[str, rsa.RSAPublicKey]:
        raise OSError("down")

    verifier = appcheck.GoogleAppCheckVerifier(PROJECT, fetch=broken, clock=lambda: 0.0, wall=lambda: NOW)
    with pytest.raises(OSError):
        verifier.verify(_token(signer))
    with pytest.raises(ValueError):
        verifier.verify(_token(signer))  # cooldown: refused without another fetch


def test_SEC_10_default_verifier_without_a_project_or_in_dev_refuses_with_no_call(monkeypatch):
    for name in ("TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError):
        appcheck.default_verifier().verify("a.b.c")
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", PROJECT)
    assert isinstance(appcheck.default_verifier(), appcheck.GoogleAppCheckVerifier)
    monkeypatch.setenv("TILO_API_DEV", "1")
    with pytest.raises(ValueError):
        appcheck.default_verifier().verify("a.b.c")
