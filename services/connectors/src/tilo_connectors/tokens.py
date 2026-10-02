"""tilo_connectors.tokens — the OAuth token broker (FR-CON-02, PRD 12.1, 16.1, SEC-02).

The only module that holds or decrypts user OAuth tokens. Each connection is one record per user and
connector: the tokens are AES-GCM encrypted under a fresh random data key, the data key is wrapped by a
`Kms` (a FakeKms in dev; Cloud KMS waits for billing, ADR-0003) with the user and connector as context,
and the store only ever sees ciphertext. Scopes and expiry stay readable beside it but are bound into
the AES-GCM context, so changing them makes the record unreadable. Nothing here logs, raises or emits
token material, a provider body or the client secret; `access_token_for_adapter` is the one call that
returns a plaintext token, for the adapters under `tilo_connectors/adapters/` only (SEC-02).

Events are parts `{type, authz, data, user_id}`. `user_id` is the seam: the broker never picks the world
or the actor (the caller checks it against the principal). The settings, KMS, store, HTTP client, clock
and `emit` are all injected; the OAuth client id and secret come from the environment the caller reads.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, NoReturn, Protocol
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ._time import add_seconds, parse_ts

_log = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_DEFAULT_EXPIRES_IN = 3600
_MAX_EXPIRES_IN = 366 * 86400
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
_DEFAULT_RETRY_RETENTION_S = 7 * 86400
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


class TokenError(Exception):
    """Base of every broker error. Messages are fixed text: never a token, a body or a secret."""


class KmsError(Exception):
    """A Kms could not decrypt (wrong context, tampering)."""


class NotConnected(TokenError):
    """No connection for this user and connector."""


class ConnectionExpired(TokenError):
    """The provider rejected the refresh (invalid_grant); the person must connect again."""


class TokenRefreshFailed(TokenError):
    """A refresh did not get through (5xx, network); the connection stays and the next call retries."""


class InsufficientScope(TokenError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("scopes not granted: " + ", ".join(missing))
        self.missing = missing


# ---- KMS ---------------------------------------------------------------------------------------


class Kms(Protocol):
    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes, *, aad: bytes) -> bytes: ...


class FakeKms:
    """Dev and CI: an envelope of a key generated at runtime for this instance; fresh nonce per call."""

    def __init__(self) -> None:
        self._aead = AESGCM(AESGCM.generate_key(bit_length=256))

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, plaintext, aad)

    def decrypt(self, ciphertext: bytes, *, aad: bytes) -> bytes:
        try:
            return self._aead.decrypt(ciphertext[:12], ciphertext[12:], aad)
        except (InvalidTag, ValueError):
            raise KmsError("the KMS could not decrypt this data") from None


class CloudKms:
    """Thin Cloud KMS adapter over an injected client (`google.cloud.kms` KeyManagementServiceClient).
    Not exercised until billing exists (ADR-0003): only encrypt and decrypt, key name `projects/...`."""

    def __init__(self, key_name: str, client: Any = None) -> None:
        self._key_name = key_name
        self._client = client

    def encrypt(self, plaintext: bytes, *, aad: bytes) -> bytes:
        request = {"name": self._key_name, "plaintext": plaintext, "additional_authenticated_data": aad}
        return bytes(self._need_client().encrypt(request=request).ciphertext)

    def decrypt(self, ciphertext: bytes, *, aad: bytes) -> bytes:
        request = {"name": self._key_name, "ciphertext": ciphertext, "additional_authenticated_data": aad}
        try:
            return bytes(self._need_client().decrypt(request=request).plaintext)
        except Exception:  # noqa: BLE001 - a provider error text must not travel
            raise KmsError("Cloud KMS could not decrypt this data") from None

    def _need_client(self) -> Any:
        if self._client is None:
            raise KmsError("no Cloud KMS client is configured")
        return self._client


# ---- settings, store, http ---------------------------------------------------------------------


@dataclass(frozen=True)
class OAuthSettings:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_base_url: str = "http://localhost:8080"

    def __post_init__(self) -> None:
        url = urlsplit(self.redirect_base_url)
        if url.scheme != "https" and not (url.scheme == "http" and url.hostname in _LOOPBACK_HOSTS):
            raise ValueError("the redirect base URL must be https (http is only for localhost)")

    @property
    def redirect_uri(self) -> str:
        return self.redirect_base_url.rstrip("/") + "/oauth/google/callback"

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> OAuthSettings:
        values: dict[str, str] = {}
        for name in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
            if not environ.get(name):
                raise ValueError(f"{name} is not set")
            values[name] = environ[name]
        base = environ.get("GOOGLE_OAUTH_REDIRECT_BASE_URL")
        kwargs = {"redirect_base_url": base} if base else {}
        return cls(values["GOOGLE_OAUTH_CLIENT_ID"], values["GOOGLE_OAUTH_CLIENT_SECRET"], **kwargs)


class TokenStore(Protocol):
    def put(self, user_id: str, connector: str, record: dict[str, Any]) -> None: ...
    def get(self, user_id: str, connector: str) -> dict[str, Any] | None: ...
    def delete(self, user_id: str, connector: str) -> None: ...
    def connectors_of(self, user_id: str) -> list[str]: ...


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()

    def put(self, user_id: str, connector: str, record: dict[str, Any]) -> None:
        with self._lock:
            self._records[(user_id, connector)] = json.dumps(record)

    def get(self, user_id: str, connector: str) -> dict[str, Any] | None:
        with self._lock:
            blob = self._records.get((user_id, connector))
        return None if blob is None else json.loads(blob)

    def delete(self, user_id: str, connector: str) -> None:
        with self._lock:
            self._records.pop((user_id, connector), None)

    def connectors_of(self, user_id: str) -> list[str]:
        with self._lock:
            return sorted(c for (u, c) in self._records if u == user_id)


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def post(self, url: str, *, data: Mapping[str, str]) -> HttpResponse: ...


@dataclass(frozen=True)
class DisconnectResult:
    revoked_at_provider: bool
    provider_error: str | None  # a short reason, never a token or a provider body


def post_form(http: HttpClient, url: str, data: Mapping[str, str]) -> tuple[int, dict[str, Any]] | None:
    """One form POST; (status, JSON object or {}), or None when it never got through. Raises nothing, so
    a provider or network error text (which can echo what was sent) never becomes our exception."""
    try:
        response = http.post(url, data=data)
        status = int(response.status_code)
    except Exception:  # noqa: BLE001
        return None
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {}
    return status, body if isinstance(body, dict) else {}


def parse_token_body(body: Mapping[str, Any], *, need_scope: bool) -> tuple[str, str | None, list[str] | None, int]:
    """(access token, refresh token, scopes, lifetime in s) of a token endpoint body, or a fixed-text
    TokenError: a wrong type must never reach an exception message, where it could echo a token."""
    access, refresh, scope = body.get("access_token"), body.get("refresh_token"), body.get("scope")
    expires = body.get("expires_in", _DEFAULT_EXPIRES_IN)
    bad = not isinstance(access, str) or not access
    bad = bad or (refresh is not None and (not isinstance(refresh, str) or not refresh))
    bad = bad or (scope is None and need_scope) or (scope is not None and not isinstance(scope, str))
    bad = bad or isinstance(expires, bool) or not isinstance(expires, int | float) or not 0 < expires <= _MAX_EXPIRES_IN
    if bad:
        raise TokenError("the token response is malformed")
    return str(access), refresh, None if scope is None else str(scope).split(), int(expires)


# ---- sealing -----------------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _ulid(now: str) -> str:
    value = (int(parse_ts(now).timestamp() * 1000) << 80) | secrets.randbits(80)
    return "".join(_CROCKFORD[(value >> shift) & 31] for shift in range(125, -1, -5))


class TokenBroker:
    def __init__(
        self,
        *,
        store: TokenStore,
        kms: Kms,
        http: HttpClient,
        settings: OAuthSettings,
        clock: Callable[[], str],
        emit: Callable[[dict[str, Any]], None],
        refresh_skew_s: int = 60,
        alert: Callable[[dict[str, Any]], None] | None = None,
        retry_store: TokenStore | None = None,
        retry_retention_s: int = _DEFAULT_RETRY_RETENTION_S,
    ) -> None:
        self._store, self._kms, self._http, self._settings = store, kms, http, settings
        self._clock, self._emit, self._skew = clock, emit, refresh_skew_s
        self._alert, self._retention = alert, retry_retention_s
        self._retry = retry_store if retry_store is not None else InMemoryTokenStore()
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._guard = threading.Lock()

    # -- public ---------------------------------------------------------------------------------

    def store_tokens(
        self,
        user_id: str,
        connector: str,
        token_response: Mapping[str, Any],
        *,
        before_established: Callable[[], None] | None = None,
    ) -> None:
        """Seal a token endpoint response and store it. No refresh token in it keeps the stored one.
        `before_established` runs once the record is stored, just before connection.established."""
        access, refresh, scopes, lifetime = parse_token_body(token_response, need_scope=True)
        with self._lock(user_id, connector):
            if not refresh:
                refresh = (self._readable(user_id, connector, self._store.get(user_id, connector)) or {}).get(
                    "refresh_token"
                )
            self._put_connected(user_id, connector, access, refresh, scopes or [], lifetime)
        if before_established is not None:
            before_established()
        self._emit_part("connection.established", user_id, connector)

    def access_token_for_adapter(self, user_id: str, connector: str, *, required_scopes: Iterable[str]) -> str:
        """The one call that returns a plaintext token; refreshes first when it is about to expire."""
        with self._lock(user_id, connector):
            record = self._store.get(user_id, connector)
            if record is None:
                raise NotConnected("no connection for this user and connector")
            if record.get("state") == "expired":
                raise ConnectionExpired("the connection expired; connect again")
            missing = [s for s in required_scopes if s not in record.get("scopes", [])]
            if missing:
                raise InsufficientScope(missing)
            payload = self._payload(user_id, connector, record)
            if payload is None:
                raise TokenError("the stored record could not be read")
            if parse_ts(add_seconds(self._clock(), self._skew)) < parse_ts(record["expires_at"]):
                return str(payload["access_token"])
            return self._refresh(user_id, connector, record, payload)

    def granted_scopes(self, user_id: str, connector: str) -> frozenset[str]:
        record = self._store.get(user_id, connector)
        if record is None or record.get("state") != "connected":
            return frozenset()
        return frozenset(record.get("scopes", []))

    def connection_state(self, user_id: str, connector: str) -> str | None:
        record = self._store.get(user_id, connector)
        return None if record is None else str(record.get("state"))

    def disconnect(self, user_id: str, connector: str) -> DisconnectResult:
        """Revoke at the provider, then delete whatever it answered (fail toward deletion). A failed
        revoke keeps the token sealed in the retry store and raises alert.raised."""
        return self._disconnect(user_id, connector, keep_retry=True)

    def delete_user(self, user_id: str) -> None:
        """Delete every token of one user, in every store (PRD 16.5). Each revoke is tried; one that
        still fails drops its token anyway and raises alert.raised, so a live grant at the provider
        is reported rather than kept."""
        for connector in self._store.connectors_of(user_id):
            self._disconnect(user_id, connector, keep_retry=False)
        self.retry_pending_revokes(user_id)
        for key in self._retry.connectors_of(user_id):
            self._retry.delete(user_id, key)
            _log.warning("a pending revoke was dropped with its user")
            self._raise_alert(user_id, _ulid(self._clock()))

    def retry_pending_revokes(self, user_id: str) -> int:
        """Retry this user's earlier failed revokes; one older than the retention limit, or that cannot
        be read, is dropped. Returns how many went through."""
        done, now = 0, parse_ts(self._clock())
        for key in self._retry.connectors_of(user_id):
            record = self._retry.get(user_id, key) or {}
            token = (self._readable(user_id, key, record, kind="revoke") or {}).get("token")
            age = (now - parse_ts(record["created_at"])).total_seconds() if "created_at" in record else None
            if not token or age is None or age > self._retention:
                self._retry.delete(user_id, key)
                _log.warning("a pending revoke for connector %r was dropped unrevoked", record.get("connector"))
            elif self._revoke(str(token)) is None:
                self._retry.delete(user_id, key)
                done += 1
        return done

    # -- internals ------------------------------------------------------------------------------

    def _lock(self, user_id: str, connector: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault((user_id, connector), threading.Lock())

    def _emit_part(self, event_type: str, user_id: str, connector: str) -> None:
        self._emit({"type": event_type, "authz": None, "data": {"connector": connector}, "user_id": user_id})

    @staticmethod
    def _context(kind: str, user_id: str, connector: str) -> bytes:
        return json.dumps([kind, user_id, connector]).encode()

    def _seal(self, kind: str, user_id: str, connector: str, plain: dict[str, Any], bind: Any) -> dict[str, Any]:
        key, nonce = AESGCM.generate_key(bit_length=256), os.urandom(12)
        context = self._context(kind, user_id, connector)
        aad = context + json.dumps(bind, sort_keys=True).encode()
        return {
            "wrapped_key": _b64(self._kms.encrypt(key, aad=context)),
            "nonce": _b64(nonce),
            "ciphertext": _b64(AESGCM(key).encrypt(nonce, json.dumps(plain).encode(), aad)),
        }

    def _payload(
        self, user_id: str, connector: str, record: dict[str, Any] | None, kind: str = "token"
    ) -> dict[str, Any] | None:
        """The decrypted tokens of a record, or None when it holds none. A copied or changed record
        raises TokenError."""
        if record is None or "ciphertext" not in record:
            return None
        bind = [record.get("scopes"), record.get("expires_at")]
        if kind == "revoke":
            bind = [record.get("alert_id"), record.get("connector"), record.get("created_at")]
        context = self._context(kind, user_id, connector)
        try:
            key = self._kms.decrypt(base64.b64decode(record["wrapped_key"]), aad=context)
            aad = context + json.dumps(bind, sort_keys=True).encode()
            plain = AESGCM(key).decrypt(base64.b64decode(record["nonce"]), base64.b64decode(record["ciphertext"]), aad)
            return dict(json.loads(plain))
        except (KmsError, InvalidTag, ValueError, KeyError, TypeError):
            raise TokenError("the stored record could not be decrypted") from None

    def _readable(
        self, user_id: str, connector: str, record: dict[str, Any] | None, kind: str = "token"
    ) -> dict[str, Any] | None:
        """Like _payload, but a record that cannot be read is None (for overwriting or deleting it)."""
        try:
            return self._payload(user_id, connector, record, kind)
        except TokenError:
            return None

    def _put_connected(
        self, user_id: str, connector: str, access: str, refresh: str | None, scopes: list[str], lifetime: int
    ) -> None:
        expires_at = add_seconds(self._clock(), lifetime)
        plain = {"access_token": access, "refresh_token": refresh}
        sealed = self._seal("token", user_id, connector, plain, [scopes, expires_at])
        record = {"v": 1, "state": "connected", "scopes": scopes, "expires_at": expires_at, **sealed}
        self._store.put(user_id, connector, record)

    def _refresh(self, user_id: str, connector: str, record: dict[str, Any], payload: dict[str, Any]) -> str:
        refresh = payload.get("refresh_token")
        if not refresh:
            self._expire(user_id, connector)  # nothing to refresh with
        form = {
            "grant_type": "refresh_token",
            "refresh_token": str(refresh),
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret,
        }
        answer = post_form(self._http, TOKEN_URL, form)
        if answer is not None and answer[0] == 400 and answer[1].get("error") == "invalid_grant":
            self._expire(user_id, connector)
        try:
            if answer is None or answer[0] != 200:
                raise TokenError("the provider did not answer with tokens")
            access, rotated, scopes, lifetime = parse_token_body(answer[1], need_scope=False)
        except TokenError:
            raise TokenRefreshFailed("the token refresh did not get through; try again later") from None
        self._put_connected(user_id, connector, access, rotated or refresh, scopes or record["scopes"], lifetime)
        return access

    def _expire(self, user_id: str, connector: str) -> NoReturn:
        """The provider will not refresh this grant: drop the tokens, keep a marker, say so once."""
        self._store.put(user_id, connector, {"v": 1, "state": "expired", "scopes": [], "expires_at": None})
        self._emit_part("connection.expired", user_id, connector)
        raise ConnectionExpired("the connection expired; connect again")

    def _revoke(self, token: str) -> str | None:
        """None when the provider revoked it, else a short reason."""
        answer = post_form(self._http, REVOKE_URL, {"token": token})
        if answer is None:
            return "the provider could not be reached"
        return None if answer[0] == 200 else f"the provider answered {answer[0]}"

    def _disconnect(self, user_id: str, connector: str, *, keep_retry: bool) -> DisconnectResult:
        with self._lock(user_id, connector):
            record = self._store.get(user_id, connector)
            if record is None:
                return DisconnectResult(False, None)
            payload = self._readable(user_id, connector, record) or {}
            token = payload.get("refresh_token") or payload.get("access_token")
            error: str | None = None
            if record.get("state") == "connected" and not token:
                error = "the stored record could not be read"
            elif token:
                error = self._revoke(str(token))
            if error is not None:
                _log.warning("revoke at the provider failed for connector %r: %s", connector, error)
                # Sealed and stored before the record is deleted: a KMS failure here leaves the record.
                self._keep_revoke_for_retry(user_id, connector, token if keep_retry else None)
            self._store.delete(user_id, connector)
        self._emit_part("connection.revoked", user_id, connector)
        return DisconnectResult(error is None and token is not None, error)

    def _keep_revoke_for_retry(self, user_id: str, connector: str, token: Any) -> None:
        """Keep the token still to be revoked sealed, keyed by its alert id, and raise alert.raised."""
        alert_id = _ulid(self._clock())
        if token:
            created = self._clock()
            bind = [alert_id, connector, created]
            sealed = self._seal("revoke", user_id, alert_id, {"token": str(token)}, bind)
            record = {"v": 1, "alert_id": alert_id, "connector": connector, "created_at": created, **sealed}
            self._retry.put(user_id, alert_id, record)
        self._raise_alert(user_id, alert_id)

    def _raise_alert(self, user_id: str, alert_id: str) -> None:
        """alert.raised carries no token. Without an alert sink the failure is only logged, loudly."""
        if self._alert is None:
            _log.error("a provider revoke failed and no alert sink is wired")
            return
        part = {"type": "alert.raised", "authz": None, "data": {"alert_id": alert_id, "card_id": None}}
        try:
            self._alert({**part, "user_id": user_id})
        except Exception:  # noqa: BLE001 - a broken sink must not stop a deletion
            _log.error("the alert sink failed for alert %s", alert_id)
