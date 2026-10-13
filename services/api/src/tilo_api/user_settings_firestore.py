"""Firestore adapter of the `SettingsStore` (FR-SET-01, ADR-0039; `tilo_api.user_settings`).

One document per person at `orgs/{org}/user_settings/{uid}`, holding the whole `user_settings.schema.json` document
(its `version` is the compare-and-set counter). It is written only by tilo-api, on the people stores' own client: a
browser never reads or writes it. A write is a transaction that stores only if the stored version is the one the
caller read. A stored document that no longer conforms, or names another owner, is refused (the route answers 503),
never read as the person's. Errors carry no document text and nothing is logged."""

from __future__ import annotations

import re
from typing import Any

from google.cloud import firestore
from tilo_policy.schemas import conforms

_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")
_USER = re.compile(r"u_[0-9A-Za-z_]{1,48}")
SCHEMA = "user_settings.schema.json"


class SettingsStoreError(RuntimeError):
    """A stored document or an address the adapter will not serve; never carries the document."""


class FirestoreSettingsStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _ref(self, org_id: str, user_id: str) -> Any:
        if not (isinstance(org_id, str) and isinstance(user_id, str) and _ORG.fullmatch(org_id)):
            raise SettingsStoreError("malformed org id")
        if _USER.fullmatch(user_id) is None:
            raise SettingsStoreError("malformed user id")
        return self._client.document(f"orgs/{org_id}/user_settings/{user_id}")

    @staticmethod
    def _checked(snap: Any, org_id: str, user_id: str) -> dict[str, Any] | None:
        if not snap.exists:
            return None
        doc = snap.to_dict()
        if not conforms(SCHEMA, doc) or doc["owner_id"] != user_id or doc["org_id"] != org_id or doc["version"] < 1:
            raise SettingsStoreError("stored settings do not conform")
        return dict(doc)

    def read(self, org_id: str, user_id: str) -> dict[str, Any] | None:
        return self._checked(self._ref(org_id, user_id).get(), org_id, user_id)

    def write(self, org_id: str, user_id: str, *, expected_version: int, document: dict[str, Any]) -> bool:
        ref = self._ref(org_id, user_id)
        if document.get("owner_id") != user_id or document.get("org_id") != org_id or not conforms(SCHEMA, document):
            raise SettingsStoreError("document does not match its address")

        @firestore.transactional  # type: ignore[misc]
        def work(tx: Any) -> bool:
            held = self._checked(ref.get(transaction=tx), org_id, user_id)
            if (held["version"] if held is not None else 0) != expected_version:
                return False
            tx.set(ref, document)
            return True

        return bool(work(self._client.transaction()))

    def erase(self, org_id: str, user_id: str) -> None:
        self._ref(org_id, user_id).delete()
