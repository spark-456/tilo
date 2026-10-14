"""tilo_channels.push_verifier: the Google ID-token check for `POST /internal/push/send` (FR-CHN-17f; SEC-REVIEW-7b B2).

The route is reachable by anyone, so a token is refused from its own header and claims (a JWT with an RS256 key id, a
Google issuer and our audience) BEFORE any certificate fetch: junk costs nothing. Those checks use public values, so a
caller can pass them; the fetch is therefore bounded (3 s, google-auth's default is 120 s), cached (15 min, counted
from the fetch), single flight (a caller that finds a fetch running is refused at once, never queued) and rate limited
(a cooldown after every attempt, an unknown key id inside the TTL waits longer). A failed fetch stores nothing and a
set past its TTL is never served. Same design as `tilo_api.schedules.GoogleOidcVerifier`; the services share no code.
`transport` has google-auth's `Request` shape; `clock` (seconds) only ages the cache.
"""

from __future__ import annotations

import base64
import binascii
import json
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

CERT_URL = "https://www.googleapis.com/oauth2/v1/certs"  # Google's public signing certificates, `{kid: x509 PEM}`
CERT_TTL_S = 900.0
CERT_FETCH_TIMEOUT_S = 3.0
CERT_RETRY_COOLDOWN_S = 10.0  # after ANY fetch attempt no other starts this soon
REFETCH_MIN_S = 30.0  # an unknown key id inside the TTL refetches at most this often
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
MAX_TOKEN = 8192


def unverified(token: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Header and claims of a JWT, NOT verified: only to refuse what is plainly not a Google token."""
    parts = token.split(".")
    if len(token) > MAX_TOKEN or len(parts) != 3:
        raise ValueError("not a JWT")
    try:
        header, claims = (json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))) for p in parts[:2])
    except (binascii.Error, ValueError) as exc:
        raise ValueError("not a JWT") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise ValueError("not a JWT")
    return header, claims


class GoogleOidcVerifier:
    def __init__(
        self, *, transport: Callable[..., Any] | None = None, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._transport, self._clock = transport, clock
        self._lock = threading.Lock()  # held by the one thread inside a fetch; never waited for
        self._snapshot: tuple[dict[str, str], float] | None = None  # (certificates, fetched_at); never mutated
        self._tried_at = float("-inf")

    def _fetch(self) -> dict[str, str]:
        if self._transport is None:
            from google.auth.transport import requests as grequests  # noqa: PLC0415

            self._transport = grequests.Request()
        response = self._transport(CERT_URL, method="GET", timeout=CERT_FETCH_TIMEOUT_S)
        if response.status != 200:
            raise ValueError("certificate fetch failed")
        certs = json.loads(response.data)
        if not isinstance(certs, dict) or not certs or not all(isinstance(v, str) for v in certs.values()):
            raise ValueError("certificate fetch returned no certificates")
        return certs

    def _usable(self, kid: str, now: float) -> dict[str, str] | None:
        """The certificates to verify with, or None when a fetch is due. Raises when none may be fetched yet."""
        snapshot, tried = self._snapshot, self._tried_at
        if snapshot is not None and 0 <= now - snapshot[1] < CERT_TTL_S:
            certs, fetched = snapshot
            if kid in certs or now - max(fetched, tried) < REFETCH_MIN_S:
                return certs
        if 0 <= now - tried < CERT_RETRY_COOLDOWN_S:
            raise ValueError("certificates unavailable")
        return None

    def _certificates(self, kid: str) -> dict[str, str]:
        certs = self._usable(kid, self._clock())
        if certs is not None:
            return certs
        if not self._lock.acquire(blocking=False):
            raise ValueError("certificate refresh in flight")
        try:
            now = self._clock()
            certs = self._usable(kid, now)  # a fetch that finished since the first look may have settled it
            if certs is not None:
                return certs
            self._tried_at = now
            try:
                fetched = self._fetch()
            except Exception:
                snapshot = self._snapshot
                if snapshot is None or not 0 <= now - snapshot[1] < CERT_TTL_S:
                    self._snapshot = None
                raise
            self._snapshot = (fetched, now)
            return fetched
        finally:
            self._lock.release()

    def verify(self, token: str, audience: str) -> Mapping[str, Any]:
        header, claims = unverified(token)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise ValueError("not a Google-signed token")
        if claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != audience:
            raise ValueError("not a token for this service")
        from google.auth import jwt  # noqa: PLC0415

        verified = jwt.decode(
            token, certs=self._certificates(kid), verify=True, audience=audience, clock_skew_in_seconds=10
        )
        if verified.get("iss") not in GOOGLE_ISSUERS:
            raise ValueError("not a Google-signed token")
        return verified


_verifier: GoogleOidcVerifier | None = None
_verifier_lock = threading.Lock()


def shared_verifier() -> GoogleOidcVerifier:
    """ONE verifier per process, so its certificate cache lives across requests."""
    global _verifier
    with _verifier_lock:
        if _verifier is None:
            _verifier = GoogleOidcVerifier()
        return _verifier
