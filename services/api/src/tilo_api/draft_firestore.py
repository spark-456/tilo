"""Durable owner follow-up drafts (FR-MTG-08), opened through the existing API store door.

Firestore create's exists=False precondition chooses one winner across processes. JSON
payloads preserve nested lists and emit markers without exposing instruction IDs in paths.
No routes, provider calls, sends, new configuration or memory fallback.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from google.api_core.exceptions import AlreadyExists

from tilo_api.followup_draft_retention import DraftRetention


def _unavailable() -> HTTPException:
    return HTTPException(503, "store_unavailable", headers={"Cache-Control": "no-store"})


class FirestoreDraftStore:
    def __init__(self, client: Any, *, org_id: str) -> None:
        if re.fullmatch(r"org_[0-9A-Za-z_]{1,48}", org_id) is None:
            raise ValueError("invalid organization")
        self._client, self._org = client, org_id
        self._owner: str | None = None
        self._retention: DraftRetention | None = None
        self._source: dict = {}
        self._expiry = 0.0
        self._clock: Callable[[], float] = lambda: 0.0
        self._before_publication: Callable[[], None] = lambda: None

    def bind(
        self,
        *,
        owner: str,
        source: dict,
        expires_at: float,
        clock: Callable[[], float],
        before_publication: Callable[[], None],
    ) -> FirestoreDraftStore:
        """New request-local authority; the shared raw adapter never holds a source callback."""
        self._path(owner, "binding")
        if not isinstance(source, dict) or not source or not callable(clock) or not callable(before_publication):
            raise ValueError("invalid draft authority")
        bound = FirestoreDraftStore(self._client, org_id=self._org)
        bound._owner, bound._source = owner, json.loads(json.dumps(source, allow_nan=False))
        bound._expiry, bound._clock, bound._before_publication = expires_at, clock, before_publication
        bound._retention = DraftRetention(
            self._client,
            org_id=self._org,
            clock=clock,
            source_valid=lambda uid, metadata: uid == owner and metadata == bound._source,
        )
        return bound

    def _authority(self, owner: str) -> DraftRetention:
        if self._retention is None or self._owner != owner:
            raise _unavailable()
        self._before_publication()  # outside SDK catches: preserve source/CAS refusal status
        now = self._clock()
        if (
            type(now) not in (int, float)
            or not math.isfinite(now)
            or type(self._expiry) not in (int, float)
            or not math.isfinite(self._expiry)
            or now >= self._expiry
        ):
            raise HTTPException(409, "followup_unavailable", headers={"Cache-Control": "no-store"})
        return self._retention

    def _path(self, user_id: str, instruction_id: str) -> str:
        if re.fullmatch(r"u_[0-9A-Za-z_]{1,48}", user_id) is None:
            raise ValueError("invalid owner")
        if not isinstance(instruction_id, str) or not instruction_id:
            raise ValueError("invalid instruction")
        key = hashlib.sha256(json.dumps([user_id, instruction_id], ensure_ascii=True).encode()).hexdigest()
        return f"orgs/{self._org}/followup_drafts/{key}"

    def get(self, user_id: str, instruction_id: str) -> dict | None:
        path = self._path(user_id, instruction_id)
        retention = self._authority(user_id)
        try:
            found = self._client.document(path).get()
            if not found.exists:
                return None
            row = found.to_dict()
        except Exception:
            raise _unavailable() from None
        self._authority(user_id)
        if not isinstance(row, dict) or row.get("expires_at") != self._expiry:
            return None
        return retention.read(user_id, instruction_id, row)

    def create(self, user_id: str, instruction_id: str, value: dict) -> bool:
        path = self._path(user_id, instruction_id)
        if not isinstance(value, dict):
            raise ValueError("draft must be an object")
        retention = self._authority(user_id)
        row = retention.envelope(user_id, instruction_id, value, source=self._source, expires_at=self._expiry)
        try:
            ref = self._client.document(path)
        except Exception:
            raise _unavailable() from None
        self._authority(user_id)  # after document lookup, immediately before SDK mutation
        try:
            ref.create(row)
        except AlreadyExists:
            return False
        except Exception:
            raise _unavailable() from None
        self._authority(user_id)
        if retention.read(user_id, instruction_id, row) is None:
            raise HTTPException(409, "followup_unavailable", headers={"Cache-Control": "no-store"})
        return True
