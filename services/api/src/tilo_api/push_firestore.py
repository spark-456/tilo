"""Firestore store for web-push subscriptions (FR-CHN-17b). One document per device at
`orgs/{org}/push/{uid}/devices/{sha256(endpoint)[:40]}` with `endpoint`, `p256dh`, `auth`; the id is a hash, so the
capability URL is in no path. A write validates with tilo-channels' `parse_subscription`, then counts the person's
devices (a bounded read) in the same transaction, so the cap holds under concurrency. Rules deny every client
(`firestore.rules` default); only this service reads or writes. Nothing here is logged."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Mapping
from typing import Any

from google.cloud import firestore
from tilo_channels.web_push import (
    PushSubscription,
    SubscriptionLimit,
    SubscriptionRefused,
    load_config,
    parse_subscription,
)
from tilo_policy.schemas import conforms

from tilo_api import deps, store_door

_opened: dict[tuple[str | None, ...], Any] = {}
_lock = threading.Lock()
_CONFIG = (store_door.ENV_STORE, store_door.ENV_PROJECT, "FIRESTORE_EMULATOR_HOST", "GOOGLE_CLOUD_PROJECT", "K_SERVICE")


def _doc_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:40]


class FirestorePushStore:
    def __init__(self, client: Any, *, org_id: str = deps.ORG_ID) -> None:
        self._client, self._org_id, self._cfg = client, org_id, load_config()

    def _devices(self, user_id: str) -> str:
        return f"orgs/{self._org_id}/push/{user_id}/devices"

    def add(self, user_id: str, raw: Mapping[str, Any]) -> PushSubscription:
        if not conforms("common.schema.json#/$defs/user_id", user_id):
            raise SubscriptionRefused("not a signed-in person's subscription")
        sub, cap = parse_subscription(raw, self._cfg), self._cfg.max_subscriptions
        path, doc_id = self._devices(user_id), _doc_id(raw["endpoint"])
        doc = {"endpoint": sub.endpoint, "p256dh": sub.p256dh, "auth": sub.auth}

        @firestore.transactional  # type: ignore[misc]
        def run(tx: Any) -> None:
            held = {d.id for d in self._client.collection(path).limit(cap + 1).stream(transaction=tx)}
            if doc_id not in held and len(held) >= cap:
                raise SubscriptionLimit("the most devices allowed")
            tx.set(self._client.document(f"{path}/{doc_id}"), doc)

        run(self._client.transaction())
        return sub

    def remove(self, user_id: str, endpoint: str) -> bool:
        ref = self._client.document(f"{self._devices(user_id)}/{_doc_id(endpoint)}")
        existed = ref.get().exists
        ref.delete()
        return bool(existed)

    def for_user(self, user_id: str) -> tuple[PushSubscription, ...]:
        docs = self._client.collection(self._devices(user_id)).limit(self._cfg.max_subscriptions + 1).stream()
        rows = [d.to_dict() or {} for d in docs]
        return tuple(PushSubscription(r["endpoint"], r["p256dh"], r["auth"]) for r in rows)


def open_push_store() -> FirestorePushStore:
    """The process's store for this config (never cached when refused); raises `ApiStoreNotConfigured`."""
    key = tuple(os.environ.get(name) for name in _CONFIG)
    with _lock:
        if key not in _opened:
            opened = store_door.open_api_store(firestore_client_factory=store_door.client_factory)
            _opened[key] = FirestorePushStore(opened.client)
        return _opened[key]
