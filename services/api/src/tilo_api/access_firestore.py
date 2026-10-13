"""The Firestore store of SEC-15 declarations (W0, completion plan 9 Oct). One document per person at
`access/{user_id}` holding `{"declaration": "visitor" | "judge", "declared_at": <server time>}` and nothing else: no
email, no name. `declare` is the one transactional create-if-absent `access.AccessStore` asks for: create the document,
and on AlreadyExists read it back; never read-then-write, never an overwrite, so two concurrent first calls leave one
winner and a stored declaration is never changed by a request. A stored value outside the two choices, a bad id and a
backend failure are errors (the gate answers 503 and lets nothing through), never "nothing declared".

`deps.get_access_store` opens it through `store_door` (`TILO_API_STORE=firestore` plus a valid project; anything else is
503 `not_configured`, never memory). A declaration never changes once made, so a positive answer is remembered by this
process (bounded); "nothing declared" is never remembered. Importing this module builds no client.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from typing import Any

from fastapi import HTTPException

from tilo_api import store_door
from tilo_api.access import Declaration

_USER_ID = re.compile(r"u_[0-9A-Za-z_]{1,48}")
_CHOICES: frozenset[str] = frozenset({"visitor", "judge"})
_COLLECTION = "access"
_REMEMBERED = 4096  # most people this process remembers a declaration for


def _check_id(user_id: Any) -> str:
    if not isinstance(user_id, str) or _USER_ID.fullmatch(user_id) is None:
        raise ValueError("user id does not match its schema")
    return user_id


def _check_choice(value: Any) -> Declaration:
    if not isinstance(value, str) or value not in _CHOICES:
        raise ValueError("declaration must be 'visitor' or 'judge'")
    return value  # type: ignore[return-value]


class FirestoreAccessStore:
    def __init__(self, client: Any) -> None:
        self._client = client
        self._seen: OrderedDict[str, Declaration] = OrderedDict()
        self._lock = threading.Lock()

    def _ref(self, user_id: str) -> Any:
        return self._client.document(f"{_COLLECTION}/{user_id}")

    def _remember(self, user_id: str, value: Declaration) -> None:
        with self._lock:
            self._seen[user_id] = value
            self._seen.move_to_end(user_id)
            while len(self._seen) > _REMEMBERED:
                self._seen.popitem(last=False)

    def get(self, user_id: str) -> Declaration | None:
        user_id = _check_id(user_id)
        with self._lock:
            if user_id in self._seen:
                return self._seen[user_id]
        snapshot = self._ref(user_id).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        try:
            value = _check_choice(data.get("declaration"))
        except ValueError:
            raise ValueError("stored declaration is not a valid declaration") from None
        self._remember(user_id, value)
        return value

    def declare(self, user_id: str, declaration: Declaration) -> Declaration:
        user_id = _check_id(user_id)
        declaration = _check_choice(declaration)
        from google.api_core import exceptions as gexc
        from google.cloud import firestore

        try:
            self._ref(user_id).create({"declaration": declaration, "declared_at": firestore.SERVER_TIMESTAMP})
        except gexc.AlreadyExists:
            stored = self.get(user_id)
            if stored is None:  # created and gone again: the store is not behaving, refuse rather than guess
                raise RuntimeError("declaration vanished after AlreadyExists") from None
            return stored
        self._remember(user_id, declaration)
        return declaration


# -- the deployed seam: one store per config, sharing one client
client_factory = store_door.client_factory
_opened: dict[tuple[str | None, ...], FirestoreAccessStore] = {}
_opening = threading.Lock()
_CONFIG = (store_door.ENV_STORE, store_door.ENV_PROJECT, "FIRESTORE_EMULATOR_HOST", "GOOGLE_CLOUD_PROJECT", "K_SERVICE")


def reset_for_tests() -> None:
    with _opening:
        _opened.clear()


def deployed() -> FirestoreAccessStore:
    """The cached store for this config, or 503: `not_configured` (never cached) or `store_unavailable`."""
    import os

    key = tuple(os.environ.get(name) for name in _CONFIG)
    with _opening:
        if key not in _opened:
            try:
                handle = store_door.open_api_store(firestore_client_factory=lambda project: client_factory(project))
            except store_door.ApiStoreNotConfigured:
                raise HTTPException(status_code=503, detail="not_configured") from None
            _opened[key] = FirestoreAccessStore(handle.client)
        return _opened[key]
