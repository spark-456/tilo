"""Durable owner follow-up drafts (FR-MTG-08), opened through the existing API store door.

Firestore create's exists=False precondition chooses one winner across processes. JSON
payloads preserve nested lists and emit markers without exposing instruction IDs in paths.
No routes, provider calls, sends, new configuration or memory fallback.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import HTTPException
from google.api_core.exceptions import AlreadyExists


def _unavailable() -> HTTPException:
    return HTTPException(503, "store_unavailable", headers={"Cache-Control": "no-store"})


class FirestoreDraftStore:
    def __init__(self, client: Any, *, org_id: str) -> None:
        if re.fullmatch(r"org_[0-9A-Za-z_]{1,48}", org_id) is None:
            raise ValueError("invalid organization")
        self._client, self._org = client, org_id

    def _path(self, user_id: str, instruction_id: str) -> str:
        if re.fullmatch(r"u_[0-9A-Za-z_]{1,48}", user_id) is None:
            raise ValueError("invalid owner")
        if not isinstance(instruction_id, str) or not instruction_id:
            raise ValueError("invalid instruction")
        key = hashlib.sha256(json.dumps([user_id, instruction_id], ensure_ascii=True).encode()).hexdigest()
        return f"orgs/{self._org}/followup_drafts/{key}"

    def get(self, user_id: str, instruction_id: str) -> dict | None:
        path = self._path(user_id, instruction_id)
        try:
            found = self._client.document(path).get()
            if not found.exists:
                return None
            value = json.loads(found.to_dict()["payload"])
            if not isinstance(value, dict):
                raise ValueError
            return value
        except Exception:
            raise _unavailable() from None

    def create(self, user_id: str, instruction_id: str, value: dict) -> bool:
        path = self._path(user_id, instruction_id)
        if not isinstance(value, dict):
            raise ValueError("draft must be an object")
        payload = json.dumps(value, ensure_ascii=True, allow_nan=False)
        try:
            self._client.document(path).create({"payload": payload})
        except AlreadyExists:
            return False
        except Exception:
            raise _unavailable() from None
        return True
