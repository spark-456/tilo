"""tilo_connectors.host_auth — who may call the internal meeting-host routes (ADR-0032 HB-01).

tilo-api sends a Google-signed ID token minted for its own runtime account, audience equal to this service's URL. No
shared secret and no API key. `GoogleOidcVerifier` refuses a token that is not a Google RS256 JWT for our audience from
its own header and claims BEFORE any certificate fetch (those checks use public values, so anyone can pass them: the
fetch is rate limited and cached). `caller_status` then compares the verified claims with the one allowed account.
Nothing here logs or echoes a token.
"""

from __future__ import annotations

import base64
import binascii
import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})  # exact, case-sensitive
CERT_URL = "https://www.googleapis.com/oauth2/v1/certs"
CERT_TTL_S = 3600.0
CERT_RETRY_S = 30.0  # at most one fetch attempt per this long, failed ones included
CERT_TIMEOUT_S = 5.0
MAX_TOKEN_CHARS = 4096


class OidcVerifier(Protocol):
    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        """The verified claims, or any exception: the caller fails closed."""
        ...


def _segment(part: str) -> dict[str, Any]:
    try:
        value = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (binascii.Error, ValueError):
        raise ValueError("not a JWT") from None
    if not isinstance(value, dict):
        raise ValueError("not a JWT")
    return value


class GoogleOidcVerifier:
    """google-auth's signature check over Google's public certificates, cached for `CERT_TTL_S`. `transport` has
    google-auth's `Request` shape and `clock` (seconds) only ages the cache; both are injectable for tests."""

    def __init__(
        self, *, transport: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._transport, self._clock = transport, clock
        self._lock = threading.Lock()
        self._certs: tuple[dict[str, str], float] | None = None  # (certificates, fetched_at)
        self._tried_at = float("-inf")

    def _fetch(self) -> dict[str, str]:
        if self._transport is None:
            from google.auth.transport import requests as grequests

            self._transport = grequests.Request()
        response = self._transport(CERT_URL, method="GET", timeout=CERT_TIMEOUT_S)
        certs = json.loads(response.data) if response.status == 200 else None
        if not isinstance(certs, dict) or not certs or not all(isinstance(v, str) for v in certs.values()):
            raise ValueError("no certificates")
        return certs

    def _certificates(self, kid: str) -> dict[str, str]:
        with self._lock:
            now = self._clock()
            held = self._certs
            if held is not None and 0 <= now - held[1] < CERT_TTL_S and kid in held[0]:
                return held[0]
            if 0 <= now - self._tried_at < CERT_RETRY_S:
                raise ValueError("certificates unavailable")  # an unknown kid or a stale set: refused, not fetched for
            self._tried_at = now
            self._certs = (self._fetch(), now)  # a failed fetch raises here and keeps nothing it did not have
            return self._certs[0]

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        parts = token.split(".") if isinstance(token, str) and len(token) <= MAX_TOKEN_CHARS else []
        if len(parts) != 3:
            raise ValueError("not a JWT")
        header, claims = _segment(parts[0]), _segment(parts[1])
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise ValueError("not a Google-signed token")
        if claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != audience:
            raise ValueError("not a token for this service")
        from google.auth import jwt

        verified = jwt.decode(
            token, certs=self._certificates(kid), verify=True, audience=audience, clock_skew_in_seconds=10
        )
        if verified.get("iss") not in GOOGLE_ISSUERS:
            raise ValueError("not a Google-signed token")
        return verified


def caller_status(claims: Mapping[str, Any], *, audience: str, caller: str) -> int | None:
    """None when the verified claims are the one allowed account; 401 for a token that is not ours or whose address
    Google did not verify, 403 for any other account (tilo-harness included)."""
    if not (
        claims.get("iss") in GOOGLE_ISSUERS and claims.get("aud") == audience and claims.get("email_verified") is True
    ):
        return 401
    return None if claims.get("email") == caller else 403
