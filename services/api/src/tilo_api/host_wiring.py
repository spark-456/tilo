"""Production wiring for the bot-hosted meeting's two Google seams (MTG-WIRE-1, FR-MTG-09, ADR-0024).

`open_host_broker` and `open_host_transport` build the token broker and the Google transport only when the
environment asks for them in full; anything else raises `HostNotConfigured` with no client built and no value echoed.
The broker keeps the bot account's grant under its own connector key (`meeting_host`), so revoking it never touches a
person's Google grant. Tokens are sealed by the broker before the store sees them; this module never logs a value.
Live use stays the user's switch (EFF-01): `LiveHttpClient` and `LiveTransport` refuse to exist without it.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Callable, Mapping
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from tilo_connectors.live import LiveHttpClient, LiveNotEnabled, LiveTransport
from tilo_connectors.tokens import CloudKms, Kms, OAuthSettings, TokenBroker

from tilo_api import events

COLLECTION = "token_grants"
_PROJECT = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_KMS_KEY = re.compile(
    r"projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/locations/[a-z0-9-]{1,40}/keyRings/[\w-]{1,63}/cryptoKeys/[\w-]{1,63}"
)
_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class HostNotConfigured(RuntimeError):
    """A setting is missing or invalid, or the live switch is off. The message names the setting, never a value."""


class FirestoreTokenStore:
    """`tokens.TokenStore` over Firestore: one document per (user, connector) at `token_grants/{user}__{connector}`.
    The record arrives already sealed by the broker, so nothing here sees a plaintext token."""

    def __init__(self, client: Any) -> None:
        self._collection = client.collection(COLLECTION)

    @staticmethod
    def _key(user_id: str, connector: str) -> str:
        if not (isinstance(user_id, str) and isinstance(connector, str) and _ID.fullmatch(user_id)
                and _ID.fullmatch(connector)):  # fmt: skip
            raise ValueError("a token record is keyed by a plain user id and connector id")
        return f"{user_id}__{connector}"

    def put(self, user_id: str, connector: str, record: dict[str, Any]) -> None:
        self._collection.document(self._key(user_id, connector)).set(
            {"user_id": user_id, "connector": connector, "record": record}
        )

    def get(self, user_id: str, connector: str) -> dict[str, Any] | None:
        snap = self._collection.document(self._key(user_id, connector)).get()
        data = snap.to_dict() if snap.exists else None
        return None if data is None else dict(data["record"])

    def delete(self, user_id: str, connector: str) -> None:
        self._collection.document(self._key(user_id, connector)).delete()

    def connectors_of(self, user_id: str) -> list[str]:
        self._key(user_id, "x")
        query = self._collection.where(filter=FieldFilter("user_id", "==", user_id))
        return sorted(str(snap.to_dict()["connector"]) for snap in query.stream())


def _default_kms(key_name: str) -> Kms:
    try:
        kms = importlib.import_module("google.cloud.kms")  # only a deployed install has it
    except ImportError:
        raise HostNotConfigured("google-cloud-kms is not installed") from None
    return CloudKms(key_name, kms.KeyManagementServiceClient())


def open_host_broker(
    env: Mapping[str, str] | None = None,
    *,
    emit: Callable[[dict[str, Any]], None],
    client_factory: Callable[[str], Any] | None = None,
    kms_factory: Callable[[str], Kms] | None = None,
    http_factory: Callable[[Mapping[str, str]], Any] | None = None,
) -> TokenBroker:
    source = os.environ if env is None else env
    project = source.get("TILO_FIRESTORE_PROJECT", "")
    if source.get("TILO_TOKEN_STORE") != "firestore" or _PROJECT.fullmatch(project) is None:
        raise HostNotConfigured("set TILO_TOKEN_STORE=firestore and a valid TILO_FIRESTORE_PROJECT")
    if source.get("LI" + "VE") != "1":  # the user's switch (EFF-01); the live clients check it again
        raise HostNotConfigured("live access is off")
    key_name = source.get("TILO_KMS_KEY", "")
    if _KMS_KEY.fullmatch(key_name) is None:
        raise HostNotConfigured("set TILO_KMS_KEY to a Cloud KMS crypto key name")
    try:
        settings = OAuthSettings.from_env(source)
        http = (http_factory or LiveHttpClient)(source)
    except LiveNotEnabled:
        raise HostNotConfigured("live access is off") from None
    except ValueError:
        raise HostNotConfigured("the Google OAuth settings are missing or invalid") from None
    client = (client_factory or (lambda name: firestore.Client(project=name)))(project)
    return TokenBroker(
        store=FirestoreTokenStore(client),
        kms=(kms_factory or _default_kms)(key_name),
        http=http,
        settings=settings,
        clock=events.now,
        emit=emit,
    )


def open_host_transport(env: Mapping[str, str] | None = None) -> LiveTransport:
    try:
        return LiveTransport(os.environ if env is None else env)
    except LiveNotEnabled:
        raise HostNotConfigured("live access is off") from None


def connection_sink(forward: Callable[[dict[str, Any]], object]) -> Callable[[dict[str, Any]], None]:
    """The broker's `emit`: hands each part to `forward` (the outbox sink) and never lets an error reach the broker."""

    def emit(part: dict[str, Any]) -> None:
        try:
            forward(part)
        except Exception:  # noqa: BLE001 - a sink failure must not break a token call
            return

    return emit
