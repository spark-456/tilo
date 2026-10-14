"""Scoped Autopilot protocols over the existing API Firestore client (FR-MTG-08).

No client creation, route registration, dispatch or memory fallback. Retention/source
erasure and publication fences must be integrated before the factory is activated.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from google.api_core.exceptions import AlreadyExists

from tilo_api.draft_firestore import FirestoreDraftStore


def _unavailable() -> HTTPException:
    return HTTPException(503, "store_unavailable", headers={"Cache-Control": "no-store"})


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True).encode()).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError("invalid JSON constant")


class _Scope:
    kind: str

    def __init__(
        self,
        client: Any,
        *,
        org_id: str,
        owner: str,
        world_id: str,
        run_id: str,
        before_publication: Callable[[], None] = lambda: None,
        drafts: FirestoreDraftStore | None = None,
    ) -> None:
        for value, prefix in ((org_id, "org"), (owner, "u"), (world_id, "w"), (run_id, "r")):
            if not isinstance(value, str) or re.fullmatch(rf"{prefix}_[0-9A-Za-z_]{{1,48}}", value) is None:
                raise ValueError("invalid scope")
        self._client, self._owner = client, owner
        self._before_publication = before_publication
        self._drafts = drafts
        self._root = f"orgs/{org_id}/followup_autopilot/{_hash([owner, world_id, run_id])}/{self.kind}"

    def _publication_document(self, path: str) -> Any:
        try:
            document = self._client.document(path)
        except Exception:
            raise _unavailable() from None
        # Outside the SDK catch: source/CAS refusals retain their original status.
        self._before_publication()
        if self._drafts is not None:
            self._drafts.state_envelope(self._owner, "write-check", {})
        return document

    def _envelope(self, path: str, value: dict) -> dict:
        if self._drafts is not None:
            return self._drafts.state_envelope(self._owner, path, value)
        return {"payload": json.dumps(value, ensure_ascii=True, allow_nan=False)}

    def _read(self, path: str, row: dict) -> dict | None:
        if self._drafts is not None:
            return self._drafts.state_read(self._owner, path, row)
        try:
            return json.loads(row["payload"], parse_constant=_reject_constant)
        except Exception:
            raise _unavailable() from None

    def _check_read(self) -> None:
        self._before_publication()
        if self._drafts is not None:
            self._drafts.state_envelope(self._owner, "read-check", {})

    def _path(self, user_id: str, key: str) -> str:
        if user_id != self._owner and not (self.kind == "cards" and user_id == "#artifacts"):
            raise PermissionError("owner scope required")
        if not isinstance(key, str) or not key:
            raise ValueError("key required")
        return f"{self._root}/{_hash([user_id, key])}"


class FirestoreCards(_Scope):
    kind = "cards"

    def _validate(self, user_id: str, value: Any) -> dict:
        if not isinstance(value, dict):
            raise ValueError("card must be an object")
        if user_id == "#artifacts" and value.get("user_id") != self._owner:
            raise PermissionError("artifact owner scope required")
        return value

    def get(self, user_id: str, key: str) -> dict | None:
        path = self._path(user_id, key)
        self._check_read()
        try:
            found = self._client.document(path).get()
            if not found.exists:
                return None
            row = found.to_dict()
        except Exception:
            raise _unavailable() from None
        self._check_read()
        value = self._read(path, row)
        if value is None and self._drafts is not None:
            return None
        try:
            return self._validate(user_id, value)
        except Exception:
            raise _unavailable() from None

    def create(self, user_id: str, key: str, value: dict) -> bool:
        path = self._path(user_id, key)
        row = self._envelope(path, self._validate(user_id, value))
        document = self._publication_document(path)
        try:
            document.create(row)
        except AlreadyExists:
            return False
        except Exception:
            raise _unavailable() from None
        return True

    def put(self, user_id: str, key: str, value: dict) -> None:
        path = self._path(user_id, key)
        row = self._envelope(path, self._validate(user_id, value))
        document = self._publication_document(path)
        try:
            document.update(row)
        except Exception:
            raise _unavailable() from None


class FirestoreStops(_Scope):
    kind = "stops"

    def add(self, user_id: str, card_id: str) -> None:
        path = self._path(user_id, card_id)
        row = self._envelope(path, {"owner": user_id, "card_id": card_id})
        document = self._publication_document(path)
        try:
            document.create(row if self._drafts is not None else {"owner": user_id, "card_id": card_id})
        except AlreadyExists:
            pass
        except Exception:
            raise _unavailable() from None

    def pending(self) -> list[tuple[str, str]]:
        self._check_read()
        try:
            snapshots = list(self._client.collection(self._root).stream())
        except Exception:
            raise _unavailable() from None
        self._check_read()
        rows = [
            self._read(f"{self._root}/{snapshot.id}", snapshot.to_dict())
            if self._drafts is not None
            else snapshot.to_dict()
            for snapshot in snapshots
        ]
        try:
            result = []
            for doc in rows:
                if doc is None:
                    continue
                owner, card = doc["owner"], doc["card_id"]
                if owner != self._owner or not isinstance(card, str) or not card:
                    raise ValueError("invalid stop")
                result.append((owner, card))
            return result
        except Exception:
            raise _unavailable() from None

    def remove(self, user_id: str, card_id: str) -> None:
        path = self._path(user_id, card_id)
        document = self._publication_document(path)
        try:
            document.delete()
        except Exception:
            raise _unavailable() from None
