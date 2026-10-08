"""Helpers for the SEC-15 / SIGNIN acceptance tests: runtime RSA keys, runtime-assembled Firebase ID tokens, an
injected key fetch. Nothing here is a secret and nothing is committed as a token; no network. Named `_signin_lib` for
the same flat-module reason as `_sec15_lib.py`."""

from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

PROJECT = "demo-tilo-signin"
NOW = 1_800_000_000.0
ISSUER_PREFIX = "https://securetoken.google.com/"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _claims(provider: str = "google.com", **over) -> dict:
    body = {
        "iss": f"{ISSUER_PREFIX}{PROJECT}",
        "aud": PROJECT,
        "auth_time": NOW - 120,
        "iat": NOW - 60,
        "exp": NOW + 3000,
        "sub": "uid" + "A1" * 10,
        "user_id": "uid" + "A1" * 10,
        "firebase": {"identities": {}, "sign_in_provider": provider},
    }
    if provider == "google.com":
        body.update(email="person@example.test", email_verified=True, name="A Person")
    body.update(over)
    return {k: v for k, v in body.items() if v is not ...}  # `...` removes a claim


def _token(key, *, kid="k1", alg="RS256", header_extra=None, **over) -> str:
    provider = over.pop("provider", "google.com")
    signing = (
        _b64(json.dumps({"alg": alg, "kid": kid, "typ": "JWT", **(header_extra or {})}).encode())
        + "."
        + _b64(json.dumps(_claims(provider, **over)).encode())
    )
    signature = key.sign(signing.encode(), padding.PKCS1v15(), hashes.SHA256())
    return signing + "." + _b64(signature)


class Fetch:
    def __init__(self, keys: dict[str, rsa.RSAPublicKey]) -> None:
        self.keys, self.calls = keys, 0

    def __call__(self) -> dict[str, rsa.RSAPublicKey]:
        self.calls += 1
        return self.keys


class FailingFetch:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise ConnectionError("keys unavailable")
