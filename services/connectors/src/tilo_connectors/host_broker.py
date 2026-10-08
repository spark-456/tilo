"""tilo_connectors.host_broker — the production broker behind the bot-hosted meeting (ADR-0032, FR-MTG-09).

The token broker stays in tilo-connectors (SEC-02): this module is its composition root. `FirestoreTokenStore` keeps one
sealed record per (user, connector) at `token_grants/{user_id}/connectors/{connector_id}` and `FirestoreRetryStore`
keeps the broker's pending revokes at `token_revoke_retry/{user_id}/pending/{key}`. Both build a path from two checked
document ids and no separator, so `u_a__b` + `c` and `u_a` + `b__c` can never share a document. Records arrive already
sealed by the broker, so nothing here sees a plaintext token.

`open_broker(env)` builds the broker only when the environment asks for it in full, and `BrokerSeam` builds it once and
remembers a failed build for 30 s. A failure names a setting, never a value or an exception's text. Nothing here logs.
No compare-and-swap yet (CON-D9): until ADR-0032 ticket T7, connectors runs one instance.
"""

from __future__ import annotations

import importlib
import os
import re
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from ._time import format_ts
from .live import LiveHttpClient, LiveNotEnabled, LiveTransport, _require_live
from .tokens import CloudKms, Kms, OAuthSettings, TokenBroker

TOKEN_COLLECTION = "token_grants"
RETRY_COLLECTION = "token_revoke_retry"
NEGATIVE_CACHE_S = 30.0

# common.schema.json: user_id and connector_id; the retry key is the broker's ULID alert id (Crockford base 32).
_USER = re.compile(r"u_[0-9A-Za-z_]{1,48}")
_CONNECTOR = re.compile(r"[a-z][a-z0-9_]{1,31}")
_RETRY_KEY = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
_PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_KMS_KEY = re.compile(
    r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z0-9-]{1,40}/keyRings/[\w-]{1,63}/cryptoKeys/[\w-]{1,63}",
    re.ASCII,
)


class BrokerNotConfigured(RuntimeError):
    """A setting is missing or invalid, or the live switch is off. The message names the setting, never a value."""


def _checked(pattern: re.Pattern[str], value: Any) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError("a token record is keyed by a plain user id and connector id")
    return value


class _NestedStore:
    """`tokens.TokenStore` over Firestore at `{root}/{user_id}/{sub}/{key}`; the document holds only the record."""

    _root = ""
    _sub = ""
    _key_pattern = _CONNECTOR

    def __init__(self, client: Any) -> None:
        self._users = client.collection(self._root)

    def _sub_collection(self, user_id: str) -> Any:
        return self._users.document(_checked(_USER, user_id)).collection(self._sub)

    def _doc(self, user_id: str, key: str) -> Any:
        return self._sub_collection(user_id).document(_checked(self._key_pattern, key))

    def put(self, user_id: str, connector: str, record: dict[str, Any]) -> None:
        self._doc(user_id, connector).set({"record": record})

    def get(self, user_id: str, connector: str) -> dict[str, Any] | None:
        snap = self._doc(user_id, connector).get()
        data = snap.to_dict() if snap.exists else None
        if data is None:
            return None
        record = data.get("record") if isinstance(data, dict) else None
        # A document that is not a record is present but unreadable: the same marker an expiry leaves, so it can be
        # disconnected or overwritten by a new consent and is never used.
        return (
            dict(record) if isinstance(record, dict) else {"v": 1, "state": "expired", "scopes": [], "expires_at": None}
        )

    def delete(self, user_id: str, connector: str) -> None:
        self._doc(user_id, connector).delete()

    def connectors_of(self, user_id: str) -> list[str]:
        ids = (str(snap.id) for snap in self._sub_collection(user_id).stream())
        return sorted(i for i in ids if self._key_pattern.fullmatch(i))


class FirestoreTokenStore(_NestedStore):
    _root, _sub, _key_pattern = TOKEN_COLLECTION, "connectors", _CONNECTOR


class FirestoreRetryStore(_NestedStore):
    """The broker's failed-revoke retry store (`retry_store`); the key is the pending revoke's alert id."""

    _root, _sub, _key_pattern = RETRY_COLLECTION, "pending", _RETRY_KEY


def _default_client(project: str) -> Any:
    try:
        firestore = importlib.import_module("google.cloud.firestore")  # only a deployed install has it
    except ImportError:
        raise BrokerNotConfigured("google-cloud-firestore is not installed") from None
    return firestore.Client(project=project)


def _default_kms(key_name: str) -> Kms:
    try:
        kms = importlib.import_module("google.cloud.kms")
    except ImportError:
        raise BrokerNotConfigured("google-cloud-kms is not installed") from None
    return CloudKms(key_name, kms.KeyManagementServiceClient())


def _now() -> str:
    return format_ts(datetime.now(UTC))


def open_broker(
    env: Mapping[str, str] | None = None,
    *,
    emit: Callable[[dict[str, Any]], None],
    alert: Callable[[dict[str, Any]], None],
    clock: Callable[[], str] = _now,
    client_factory: Callable[[str], Any] | None = None,
    kms_factory: Callable[[str], Kms] | None = None,
    http_factory: Callable[[Mapping[str, str]], Any] | None = None,
) -> TokenBroker:
    """The broker over Firestore and Cloud KMS, or `BrokerNotConfigured`. Live use stays the user's switch (EFF-01).
    `emit` and `alert` have no default: a connection part or a failed bot revoke must reach someone (ADR-0032 T3)."""
    source = os.environ if env is None else env
    project = source.get("TILO_FIRESTORE_PROJECT", "")
    if source.get("TILO_TOKEN_STORE") != "firestore" or _PROJECT.fullmatch(project) is None:
        raise BrokerNotConfigured("set TILO_TOKEN_STORE=firestore and a valid TILO_FIRESTORE_PROJECT")
    try:
        _require_live(source)  # live.py's own gate; its LiveHttpClient checks again
    except LiveNotEnabled:
        raise BrokerNotConfigured("live access is off") from None
    key_name = source.get("TILO_KMS_KEY", "")
    if _KMS_KEY.fullmatch(key_name) is None:
        raise BrokerNotConfigured("set TILO_KMS_KEY to a Cloud KMS crypto key name")
    try:
        settings = OAuthSettings.from_env(source)
        http = (http_factory or LiveHttpClient)(source)
    except LiveNotEnabled:
        raise BrokerNotConfigured("live access is off") from None
    except ValueError:
        raise BrokerNotConfigured("the Google OAuth settings are missing or invalid") from None
    client = (client_factory or _default_client)(project)
    return TokenBroker(
        store=FirestoreTokenStore(client),
        kms=(kms_factory or _default_kms)(key_name),
        http=http,
        settings=settings,
        clock=clock,
        emit=emit,
        alert=alert,
        retry_store=FirestoreRetryStore(client),
    )


def open_transport(env: Mapping[str, str] | None = None) -> LiveTransport:
    """The one transport that reaches Google with a token (tilo-connectors only), or `BrokerNotConfigured`."""
    try:
        return LiveTransport(os.environ if env is None else env)
    except LiveNotEnabled:
        raise BrokerNotConfigured("live access is off") from None


class BrokerSeam:
    """Builds the broker once. A failed build is remembered for `NEGATIVE_CACHE_S`, so a misconfigured service does not
    rebuild clients on every request, and then the next call tries again: a fixed setting needs no restart.

    The build runs outside the lock (a slow client must not stall every request); two callers may build at once and the
    first to finish wins, the other's is dropped unused. The environment is read when it is needed (`env=None` reads the
    process environment each time) and a given mapping is let go once a build succeeded, so the OAuth client secret is
    not kept as an attribute for the life of the process."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        *,
        emit: Callable[[dict[str, Any]], None],
        alert: Callable[[dict[str, Any]], None],
        opener: Callable[..., Any] = open_broker,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = NEGATIVE_CACHE_S,
    ) -> None:
        self._env: Mapping[str, str] | None = env
        self._emit, self._alert, self._opener = emit, alert, opener
        self._clock, self._ttl = clock, ttl_s
        self._lock = threading.Lock()
        self._built: Any = None
        self._failed_at: float | None = None
        self._reason = "not_configured"

    def get(self) -> Any:
        with self._lock:
            if self._built is not None:
                return self._built
            now = self._clock()
            if self._failed_at is not None and now - self._failed_at < self._ttl:
                raise BrokerNotConfigured(self._reason)
            env, opener = self._env, self._opener
        reason, built = "not_configured", None
        try:
            built = opener(env, emit=self._emit, alert=self._alert)
        except BrokerNotConfigured as error:
            reason = str(error)  # ours: it names a setting, never a value
        except Exception:  # noqa: BLE001 - any other error text may echo a secret
            pass
        with self._lock:
            if self._built is None and built is not None:
                self._built, self._failed_at, self._env, self._opener = built, None, None, _spent
            if self._built is not None:
                return self._built
            self._failed_at, self._reason = now, reason
        raise BrokerNotConfigured(reason)


def _spent(*_: Any, **__: Any) -> Any:
    raise BrokerNotConfigured("the broker is built already")
