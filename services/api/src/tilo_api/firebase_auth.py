"""SEC-15 / SIGNIN: app sign-in at the tilo-api edge (PRD 6 platform row "Firebase Authentication: Google sign-in and
anonymous demo sessions"; PRD 16.1: Tilo never handles passwords; PRD R-06; BQ-SIGNIN-2, BQ-SIGNIN-3).

The web client sends the person's Firebase ID token in `Authorization: Bearer`. `FirebaseIdTokenVerifier` checks it
against Google's securetoken keys, with the same key cache, single flight and cooldown as `tilo_api.appcheck` (they
share `JwksKeyCache`); `deps.get_current_principal` turns the verified claims into a `Principal`. Deterministic code
only: no model decides who is let in, and nothing in a request (other than the signed token) sets the user or
`full_session`.

What is accepted: RS256 only; `aud` exactly the project id (a string); `iss` exactly
`https://securetoken.google.com/<project>`; `sub` a non-empty string of at most 128 characters; `exp` in the future;
`iat` and `auth_time` numbers not in the future; the provider `google.com` (with a verified email) or `anonymous`
and nothing else. Every refusal carries a fixed lower-case code written here, never text from the token. Dev mode
(`TILO_API_DEV=1`) and an unconfigured project open no socket: the default verifier refuses without a fetch.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeGuard

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from tilo_api.appcheck import JwksKeyCache, RefuseAll, TokenRefused, b64url_decode, fetch_jwks

if TYPE_CHECKING:
    from tilo_api.deps import Principal

__all__ = [
    "ISSUER_PREFIX", "JWKS_URL", "MAX_TOKEN_CHARS", "FirebaseIdTokenVerifier", "FirebaseVerifier", "TokenRefused",
    "bearer_token", "channel_of", "default_verifier", "principal_from_claims", "user_id_for",
]  # fmt: skip

JWKS_URL = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
ISSUER_PREFIX = "https://securetoken.google.com/"
MAX_TOKEN_CHARS = 4096  # a real ID token is about 1 KiB; a longer one is refused without being parsed or verified
PROVIDERS = frozenset({"google.com", "anonymous"})  # Tilo never handles passwords: no other sign-in method
_MAX_SUB_CHARS = 128  # Firebase's own uid limit
_CLOCK_SKEW_S = 10.0  # a token issued "now" by Google's clock may be a few seconds ahead of ours
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9._-]+")
_BEARER = re.compile(r"(?i:bearer) ([^ ]+)")

Channel = Literal["web", "mobile_web"]


class FirebaseVerifier(Protocol):
    def verify(self, token: str) -> Mapping[str, Any]:
        """The token's claims; raises for any token it refuses or cannot check."""
        ...


def _fetch_securetoken_keys() -> dict[str, rsa.RSAPublicKey]:
    return fetch_jwks(JWKS_URL)


def _is_number(value: object) -> TypeGuard[float]:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an integer too large for a float (a hand-made token): not a time, so the caller refuses it
        return False


class FirebaseIdTokenVerifier(JwksKeyCache):
    """Verifies a Firebase ID token (RS256) for one Firebase project. The header and claims are read first, from
    public values only, and a token that cannot pass the claim checks is refused before any key is fetched. `fetch`
    and the clocks are injectable; tests and dev never reach the default fetch."""

    def __init__(
        self,
        project: str,
        *,
        fetch: Callable[[], dict[str, rsa.RSAPublicKey]] = _fetch_securetoken_keys,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(fetch, clock)
        self._project, self._wall = project, wall

    def _check_claims(self, claims: dict[str, Any], now: float) -> None:
        if not isinstance(claims.get("aud"), str) or claims["aud"] != self._project:
            raise TokenRefused("wrong_project")
        if claims.get("iss") != f"{ISSUER_PREFIX}{self._project}":
            raise TokenRefused("wrong_issuer")
        sub = claims.get("sub")
        if not isinstance(sub, str) or not 0 < len(sub) <= _MAX_SUB_CHARS:
            raise TokenRefused("bad_subject")
        exp = claims.get("exp")
        if not _is_number(exp) or exp <= now:
            raise TokenRefused("expired")
        for name in ("iat", "auth_time", "nbf"):
            value = claims.get(name, 0 if name == "nbf" else None)
            if not _is_number(value) or value > now + _CLOCK_SKEW_S:
                raise TokenRefused("bad_time" if name != "nbf" else "not_yet_valid")
        firebase = claims.get("firebase")
        if not isinstance(firebase, dict):
            raise TokenRefused("sign_in_method_not_allowed")
        provider = firebase.get("sign_in_provider")
        if not isinstance(provider, str) or provider not in PROVIDERS:
            raise TokenRefused("sign_in_method_not_allowed")
        if "tenant" in firebase:  # a multi-tenant (Identity Platform) token: Tilo has no tenants, so none is accepted
            raise TokenRefused("tenant_not_allowed")
        if provider == "google.com" and claims.get("email_verified") is not True:
            raise TokenRefused("email_not_verified")

    def verify(self, token: str) -> Mapping[str, Any]:
        parts = token.split(".")
        if len(parts) != 3 or len(token) > MAX_TOKEN_CHARS:
            raise TokenRefused("not_a_jwt")
        try:
            header, claims, signature = (
                json.loads(b64url_decode(parts[0])),
                json.loads(b64url_decode(parts[1])),
                b64url_decode(parts[2]),
            )
        except (ValueError, RecursionError) as exc:  # binascii.Error and UnicodeDecodeError are ValueErrors
            raise TokenRefused("not_a_jwt") from exc
        if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "RS256":
            raise TokenRefused("not_an_id_token")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenRefused("not_an_id_token")
        self._check_claims(claims, self._wall())
        key = self._keys(kid).get(kid)
        if key is None:
            raise TokenRefused("unknown_key")
        try:
            key.verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, UnicodeEncodeError) as exc:
            raise TokenRefused("bad_signature") from exc
        return claims


@functools.cache
def _google_verifier(project: str) -> FirebaseIdTokenVerifier:
    return FirebaseIdTokenVerifier(project)  # one per project, so its key cache lives across requests


def default_verifier() -> FirebaseVerifier:
    """What `deps.get_firebase_verifier` returns: Google's keys for the API's own project (the Firestore project
    setting, else `GOOGLE_CLOUD_PROJECT`, as App Check). Dev mode, or no project, gets a verifier that refuses
    without any call: a dev flag never trusts a token."""
    from tilo_api import dev  # noqa: PLC0415  (dev imports deps, which imports this module)

    if dev.dev_enabled():
        return RefuseAll("dev_mode")
    project = (os.environ.get("TILO_FIRESTORE_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project:
        return RefuseAll("no_project")
    return _google_verifier(project)


def bearer_token(values: list[str]) -> str | None:
    """The token of exactly one `Authorization: Bearer <token>` header, or None for anything else (no header, two
    headers, another scheme, a value that is not a plain run of token characters, or one over the size cap)."""
    if len(values) != 1 or len(values[0]) > MAX_TOKEN_CHARS + len("Bearer "):
        return None
    found = _BEARER.fullmatch(values[0])
    return found.group(1) if found and _TOKEN_CHARS.fullmatch(found.group(1)) else None


def channel_of(header: str | None) -> Channel:
    """BQ-SIGNIN-3: `X-Tilo-Channel: mobile_web` says the person is on a phone; anything else is `web`. Both are web
    sign-in channels with the same authority, so a client hint widens nothing; `email` only comes from a signed link."""
    return "mobile_web" if header == "mobile_web" else "web"


def user_id_for(uid: str) -> str:
    """A stable, collision-free `user_id` (`^u_[0-9A-Za-z_]{1,48}$`) for a Firebase uid: a domain-separated SHA-256
    of the uid, 192 bits in hex. Never the dev owner, never the uid itself, never the email."""
    digest = hashlib.sha256(b"tilo/firebase-uid/" + uid.encode("utf-8", "surrogatepass")).hexdigest()
    return f"u_{digest[:48]}"


def principal_from_claims(claims: Mapping[str, Any], *, channel: Channel) -> Principal:
    """The `Principal` for verified claims: role owner (each person owns their own worlds), `full_session` True only
    for a Google sign-in (BQ-XWORLD-10: an anonymous demo session stays bound to its own world). Raises
    `TokenRefused` for claims of the wrong shape. The principal never carries the email or name."""
    from tilo_api.deps import Principal  # noqa: PLC0415  (deps imports this module)

    sub, firebase = claims.get("sub") if isinstance(claims, Mapping) else None, claims.get("firebase")
    if not isinstance(sub, str) or not 0 < len(sub) <= _MAX_SUB_CHARS or not isinstance(firebase, dict):
        raise TokenRefused("bad_claims")
    full = firebase.get("sign_in_provider") == "google.com"
    return Principal(
        user_id=user_id_for(sub),
        role="owner",
        channel=channel,
        full_session=full,
        demo_session=not full,  # an anonymous demo session gets replay models only (BQ-SIGNIN-10)
    )
