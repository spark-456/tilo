"""SEC-10: Firebase App Check at the tilo-api edge (PRD 16 "Rate limits, App Check and spend caps"; PRD 6.2).

The web client sends a short-lived App Check token in `X-Firebase-AppCheck`. `AppCheckGate` is a pure ASGI
middleware beside `AccessGate`; it asks `deps.get_app_check_verifier()` whether the token is genuine. Enforcement is
the flag `TILO_APPCHECK_ENFORCE`, read on every request, and ONLY exactly "1" turns it on; the default is off
(infra/ACCESS.md section 7: the owner alone flips it). Off, a missing, empty, refused or unverifiable token is logged
once as a WARNING on `tilo_api.appcheck` (never the token, never the error text) and the answer is unchanged. On, it
is a 401 and the route never runs. `/health`, `/healthz` and `POST /internal/schedules/tick` (its own Google OIDC
check, FR-AGT-14b) are never checked: probes and Cloud Scheduler carry no App Check token.

Deterministic code only: no model decides who is let in. Dev mode (`TILO_API_DEV=1`) and CI open no socket: the
dev verifier refuses every token without a fetch, and a verifier with no project configured refuses before one.
"""

from __future__ import annotations

import base64
import binascii
import functools
import json
import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("tilo_api.appcheck")

HEADER = b"x-firebase-appcheck"  # ASGI header names are lower-case bytes
ENFORCE_ENV = "TILO_APPCHECK_ENFORCE"
REFUSED = "A valid App Check token is required."

# Never checked, in either mode (a test pins this list).
EXEMPT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("GET", "/health"), ("GET", "/healthz"), ("POST", "/internal/schedules/tick")}
)

MAX_TOKEN_CHARS = 4096  # a real token is about 1 KiB; a longer one is refused without being parsed or verified

JWKS_URL = "https://firebaseappcheck.googleapis.com/v1/jwks"
ISSUER_PREFIX = "https://firebaseappcheck.googleapis.com/"
JWKS_TTL_S = 900.0  # a fetched key set is trusted this long, counted from the fetch
JWKS_FETCH_TIMEOUT_S = 3.0
# past its TTL a snapshot may still serve a KNOWN key id for this long, only while a refresh is in flight or has
# just failed (BQ-SEC10-4)
JWKS_STALE_GRACE_S = 3600.0
JWKS_RETRY_COOLDOWN_S = 10.0  # after ANY fetch attempt no other starts this soon (a dead endpoint costs one per 10 s)
_REFETCH_MIN_S = 30.0  # an unknown key id inside the TTL refetches at most this often
_MAX_JWKS_BYTES = 65536
_CLOCK_SKEW_S = 10.0


class TokenRefused(ValueError):
    """A token the verifier refuses. `code` is one of a fixed set of words written in this module, never taken from
    the token or from a library's text, so the gate can log WHY without ever logging the token."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AppCheckVerifier(Protocol):
    def verify(self, token: str) -> Mapping[str, Any]:
        """The token's claims; raises for any token it refuses or cannot check."""
        ...


def b64url_decode(part: str) -> bytes:
    """Unpadded base64url, as a JWT part is written (shared with `firebase_auth`)."""
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def fetch_jwks(url: str) -> dict[str, rsa.RSAPublicKey]:
    """The RSA keys of one JWKS endpoint, by key id (shared with `tilo_api.firebase_auth`)."""
    import requests  # noqa: PLC0415  (kept out of import time: nothing here opens a socket until a token needs a key)

    response = requests.get(url, timeout=JWKS_FETCH_TIMEOUT_S)
    if response.status_code != 200 or len(response.content) > _MAX_JWKS_BYTES:
        raise ValueError("key fetch failed")
    keys: dict[str, rsa.RSAPublicKey] = {}
    for jwk in response.json().get("keys", []):
        if jwk.get("kty") == "RSA" and isinstance(jwk.get("kid"), str):
            numbers = rsa.RSAPublicNumbers(
                int.from_bytes(b64url_decode(jwk["e"]), "big"), int.from_bytes(b64url_decode(jwk["n"]), "big")
            )
            keys[jwk["kid"]] = numbers.public_key()
    if not keys:
        raise ValueError("key fetch returned no keys")
    return keys


def _fetch_jwks() -> dict[str, rsa.RSAPublicKey]:
    return fetch_jwks(JWKS_URL)


class JwksKeyCache:
    """One immutable snapshot of a JWKS, refreshed single-flight: the snapshot is read without a lock; a refresh takes
    the lock with a non-blocking acquire, so at most one thread is inside a fetch and a caller that finds one running
    is refused at once. A failed fetch stores nothing new, a snapshot past `JWKS_TTL_S` is served only inside the
    stale grace (`JWKS_STALE_GRACE_S`, for a key id it already holds, and only while a refresh is in flight or has
    just failed: after a restart or a TTL refresh a valid token is not refused for the fetch's sake; a true cold
    start, with nothing held yet, still refuses until the first fetch lands), and no
    fetch starts within `JWKS_RETRY_COOLDOWN_S` of another. Shared by the App Check and Firebase ID-token
    verifiers."""

    def __init__(self, fetch: Callable[[], dict[str, rsa.RSAPublicKey]], clock: Callable[[], float]) -> None:
        self._fetch, self._clock = fetch, clock
        self._lock = threading.Lock()
        self._snapshot: tuple[dict[str, rsa.RSAPublicKey], float] | None = None
        self._tried_at = float("-inf")

    def _stale(self, kid: str, now: float) -> dict[str, rsa.RSAPublicKey] | None:
        """The held keys when the snapshot is past its TTL but inside the grace and holds `kid`, else None."""
        snapshot = self._snapshot
        if snapshot is None:
            return None
        keys, fetched = snapshot
        age = now - fetched
        return keys if JWKS_TTL_S <= age < JWKS_TTL_S + JWKS_STALE_GRACE_S and kid in keys else None

    def _usable(self, kid: str, now: float) -> dict[str, rsa.RSAPublicKey] | None:
        snapshot, tried = self._snapshot, self._tried_at
        if snapshot is not None and 0 <= now - snapshot[1] < JWKS_TTL_S:
            keys, fetched = snapshot
            if kid in keys or now - max(fetched, tried) < _REFETCH_MIN_S:
                return keys
        if 0 <= now - tried < JWKS_RETRY_COOLDOWN_S:  # a refresh has just run (and failed, or nothing new was found)
            stale = self._stale(kid, now)
            if stale is not None:
                return stale
            raise TokenRefused("keys_unavailable")
        return None

    def _keys(self, kid: str) -> dict[str, rsa.RSAPublicKey]:
        now = self._clock()
        keys = self._usable(kid, now)
        if keys is not None:
            return keys
        if not self._lock.acquire(blocking=False):
            stale = self._stale(kid, now)
            if stale is not None:
                return stale  # a refresh is running: the held keys serve a known key id meanwhile
            raise TokenRefused("key_refresh_in_flight")
        try:
            now = self._clock()
            keys = self._usable(kid, now)
            if keys is not None:
                return keys
            self._tried_at = now
            try:
                fetched = self._fetch()
            except Exception:
                now = self._clock()  # the fetch took time: the grace is judged at the moment it failed
                snapshot = self._snapshot
                if snapshot is None or not 0 <= now - snapshot[1] < JWKS_TTL_S + JWKS_STALE_GRACE_S:
                    self._snapshot = None  # beyond the grace nothing is kept
                else:
                    stale = self._stale(kid, now)
                    if stale is not None:
                        return stale  # the fetch just failed: a known key id is still served inside the grace
                raise
            self._snapshot = (fetched, now)
            return fetched
        finally:
            self._lock.release()


class GoogleAppCheckVerifier(JwksKeyCache):
    """Verifies an App Check JWT (RS256) against Google's JWKS for one Firebase project.

    The signature, `exp`, `nbf`, `iss` (Firebase App Check) and `aud` (`projects/<project>`) are all checked. The
    header and claims are read first, from public values only, and a token that cannot pass them is refused before
    any key is fetched. Keys live in one immutable snapshot (read without a lock); a refresh takes the lock with a
    non-blocking acquire, so at most one thread is inside a fetch and a caller that finds one running is refused at
    once. A failed fetch stores nothing and a snapshot past `JWKS_TTL_S` is served only inside the stale grace.
    `fetch` and the clocks are injectable; tests and dev never reach the default fetch."""

    def __init__(
        self,
        project: str,
        *,
        fetch: Callable[[], dict[str, rsa.RSAPublicKey]] = _fetch_jwks,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(fetch, clock)
        self._audience = f"projects/{project}"
        self._wall = wall

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
        except (binascii.Error, ValueError) as exc:
            raise TokenRefused("not_a_jwt") from exc
        if not isinstance(header, dict) or not isinstance(claims, dict) or header.get("alg") != "RS256":
            raise TokenRefused("not_an_app_check_token")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenRefused("not_an_app_check_token")
        audience, issuer = claims.get("aud"), claims.get("iss")
        if self._audience not in (audience if isinstance(audience, list) else [audience]):
            raise TokenRefused("wrong_project")
        if not isinstance(issuer, str) or not issuer.startswith(ISSUER_PREFIX) or issuer == ISSUER_PREFIX:
            raise TokenRefused("wrong_issuer")
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise TokenRefused("no_app")
        key = self._keys(kid).get(kid)
        if key is None:
            raise TokenRefused("unknown_key")
        try:
            key.verify(signature, f"{parts[0]}.{parts[1]}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
        except (InvalidSignature, UnicodeEncodeError) as exc:
            raise TokenRefused("bad_signature") from exc
        now = self._wall()
        exp, nbf = claims.get("exp"), claims.get("nbf", 0)
        numbers = (int, float)
        if not isinstance(exp, numbers) or isinstance(exp, bool) or exp < now - _CLOCK_SKEW_S:
            raise TokenRefused("expired")
        if not isinstance(nbf, numbers) or isinstance(nbf, bool) or nbf > now + _CLOCK_SKEW_S:
            raise TokenRefused("not_yet_valid")
        return claims


class RefuseAll:
    """Dev mode and an unconfigured project: nothing is fetched, nothing is verified."""

    def __init__(self, why: str) -> None:
        self._why = why

    def verify(self, token: str) -> Mapping[str, Any]:
        raise TokenRefused(self._why)


@functools.cache
def _google_verifier(project: str) -> GoogleAppCheckVerifier:
    return GoogleAppCheckVerifier(project)  # one per project, so its key cache lives across requests


def default_verifier() -> AppCheckVerifier:
    """What `deps.get_app_check_verifier` returns: Google's keys for the API's own project (the Firestore project
    setting, else `GOOGLE_CLOUD_PROJECT`). Dev mode, or no project, gets a verifier that refuses without any call."""
    from tilo_api import dev  # noqa: PLC0415  (dev imports deps, which imports this module)

    if dev.dev_enabled():
        return RefuseAll("dev_mode")
    project = (os.environ.get("TILO_FIRESTORE_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project:
        return RefuseAll("no_project")
    return _google_verifier(project)


def enforcing(env: Mapping[str, str] | None = None) -> bool:
    return (os.environ if env is None else env).get(ENFORCE_ENV) == "1"  # exactly "1", read on every request


def _token_of(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == HEADER:
            return str(value.decode("latin-1"))
    return ""


_MISSING_LOG_EVERY_S = (
    60.0  # a flood of tokenless requests is one log line a minute, with a count, never one per request
)
_missing_log = {"at": float("-inf"), "skipped": 0}
_missing_lock = threading.Lock()


def _warn_missing(clock: Callable[[], float] = time.monotonic) -> None:
    """Logs the missing-token warning at most once per `_MISSING_LOG_EVERY_S` per process, naming how many were left
    out since the last line (an unauthenticated caller must not be able to fill the log or the bill)."""
    now = clock()
    with _missing_lock:
        if now - _missing_log["at"] < _MISSING_LOG_EVERY_S:
            _missing_log["skipped"] += 1
            return
        skipped, _missing_log["at"], _missing_log["skipped"] = _missing_log["skipped"], now, 0
    suffix = f", {skipped} more since the last line" if skipped else ""
    logger.warning("App Check token missing from the request (reason=missing%s)", suffix)


def _is_verified(scope: Scope, token: str) -> bool:
    """True for a genuine token. Anything else (no token, a refused one, a verifier that fails) is False and logged
    once as a warning with a fixed reason code (`TokenRefused.code`, or `verifier_failed:<error type>` for any other
    failure of the verifier), never the token or an error text."""
    if not token:
        _warn_missing()
        return False
    from tilo_api import deps  # noqa: PLC0415  (deps imports this module)

    try:
        factory = scope["app"].dependency_overrides.get(deps.get_app_check_verifier, deps.get_app_check_verifier)
        factory().verify(token)
    except Exception as exc:
        reason = exc.code if isinstance(exc, TokenRefused) else f"verifier_failed:{type(exc).__name__}"
        logger.warning("App Check token not verified (reason=%s)", reason)
        return False
    return True


class AppCheckGate:
    """Pure ASGI middleware, before routing. `lifespan` and any scope type it does not know pass untouched (the
    access gate owns those); a `websocket` is closed (1008) before it is accepted when it is refused."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind not in {"http", "websocket"} or (kind == "http" and (scope["method"], scope["path"]) in EXEMPT_ROUTES):
            await self.app(scope, receive, send)
            return
        token = _token_of(scope)
        verified = await run_in_threadpool(_is_verified, scope, token)  # verify may fetch keys: never on the loop
        if verified or not enforcing():
            await self.app(scope, receive, send)
        elif kind == "http":
            await JSONResponse({"detail": REFUSED, "code": "app_check_required"}, status_code=401)(scope, receive, send)
        else:
            await receive()
            await send({"type": "websocket.close", "code": 1008})
