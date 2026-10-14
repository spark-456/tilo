"""FR-MTG-08/FR-MEM-09 metadata policy for the existing durable follow-up draft collection.

The scoped caller supplies trusted source metadata, its retention deadline and a fresh
source validator. Bodies and emit markers share that policy. The existing draft adapter
must atomically create this envelope with its payload, then apply read() to every read.
Cleanup uses the same store-door client and collection; no client/store/env is created here.
Meeting deletion calls erase_meeting_complete after its tombstone. Owner erasure and the
expiry sweep still need explicit production wiring before activation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from typing import Any, TypeGuard

from fastapi import HTTPException
from google.api_core.exceptions import FailedPrecondition, NotFound
from google.cloud.firestore_v1.base_query import FieldFilter


def _closed(status: int = 503) -> HTTPException:
    return HTTPException(
        status, "followup_unavailable" if status == 409 else "store_unavailable", headers={"Cache-Control": "no-store"}
    )


def _id(value: str, prefix: str) -> str:
    if not isinstance(value, str) or re.fullmatch(prefix + r"_[0-9A-Za-z_]{1,48}", value) is None:
        raise ValueError("invalid identity")
    return value


def _finite(value: Any) -> TypeGuard[int | float]:
    return type(value) in (int, float) and math.isfinite(value)


class DraftRetention:
    def __init__(
        self, client: Any, *, org_id: str, clock: Callable[[], float], source_valid: Callable[[str, dict], bool]
    ) -> None:
        self.client, self.org = client, _id(org_id, "org")
        self.clock, self.source_valid = clock, source_valid
        self.collection = f"orgs/{self.org}/followup_drafts"

    def path(self, owner: str, instruction_id: str) -> str:
        _id(owner, "u")
        if not isinstance(instruction_id, str) or not instruction_id:
            raise ValueError("invalid instruction")
        key = hashlib.sha256(json.dumps([owner, instruction_id], ensure_ascii=True).encode()).hexdigest()
        return f"{self.collection}/{key}"

    def _alive(self, owner: str, source: dict, expires_at: object) -> bool:
        now = self.clock()
        if not _finite(now) or not _finite(expires_at) or now >= expires_at:
            return False
        try:
            return self.source_valid(owner, source) is True
        except Exception:
            raise _closed() from None

    def envelope(self, owner: str, instruction_id: str, value: dict, *, source: dict, expires_at: float) -> dict:
        key = self.path(owner, instruction_id).rsplit("/", 1)[1]
        if not isinstance(value, dict) or not isinstance(source, dict) or not source:
            raise ValueError("invalid draft metadata")
        if not self._alive(owner, source, expires_at):
            raise _closed(409)
        return {
            "retention_version": 1, "org_id": self.org, "owner": owner, "instruction_hash": key,
            "source": json.loads(json.dumps(source, allow_nan=False)), "expires_at": expires_at,
            "created_at": self.clock(), "payload": json.dumps(value, ensure_ascii=True, allow_nan=False),
        }  # fmt: skip

    def read(self, owner: str, instruction_id: str, row: dict) -> dict | None:
        key = self.path(owner, instruction_id).rsplit("/", 1)[1]
        if (
            not isinstance(row, dict)
            or row.get("retention_version") != 1
            or row.get("org_id") != self.org
            or row.get("owner") != owner
            or row.get("instruction_hash") != key
            or not isinstance(row.get("source"), dict)
            or not row["source"]
            or not _finite(row.get("created_at"))
            or not self._alive(owner, row["source"], row.get("expires_at"))
        ):
            return None  # legacy/unbound rows also fail closed; no content or marker bypass
        try:
            value = json.loads(row["payload"])
        except (KeyError, ValueError, TypeError):
            raise _closed() from None
        if not isinstance(value, dict):
            raise _closed()
        return value if self._alive(owner, row["source"], row["expires_at"]) else None

    def _cleanup(self, field: str, operator: str, value: Any, limit: int) -> int:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("invalid cleanup limit")
        removed = 0
        try:
            query = (
                self.client.collection(self.collection).where(filter=FieldFilter(field, operator, value)).limit(limit)
            )
            for found in query.stream():
                row = found.to_dict()
                if (
                    not isinstance(row, dict)
                    or row.get("org_id") != self.org
                    or re.fullmatch(r"[0-9a-f]{64}", found.id) is None
                    or (field == "owner" and row.get("owner") != value)
                    or (field == "expires_at" and (not _finite(row.get(field)) or row[field] > value))
                ):
                    raise ValueError("invalid retention row")
                try:
                    self.client.document(f"{self.collection}/{found.id}").delete(
                        option=self.client.write_option(last_update_time=found.update_time)
                    )
                    removed += 1
                except (FailedPrecondition, NotFound):
                    continue  # changed rows require a fresh indexed pass; never delete the replacement
        except Exception:
            raise _closed() from None
        return removed  # removed in this bounded pass; caller must reread before reporting erasure complete

    def erase_owner(self, owner: str, *, limit: int = 200) -> int:
        return self._cleanup("owner", "==", _id(owner, "u"), limit)

    def purge_expired(self, *, limit: int = 200) -> int:
        now = self.clock()
        if not _finite(now):
            raise _closed()
        return self._cleanup("expires_at", "<=", now, limit)

    def _meeting_query(self, owner: str, meeting_id: str, limit: int) -> Any:
        _id(owner, "u")
        _id(meeting_id, "mt")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("invalid cleanup limit")
        return (
            self.client.collection(self.collection)
            .where(filter=FieldFilter("owner", "==", owner))
            .where(filter=FieldFilter("source.meeting_id", "==", meeting_id))
            .limit(limit)
        )

    def erase_meeting(self, owner: str, meeting_id: str, *, limit: int = 200) -> int:
        """One indexed pass, with snapshot preconditions; replacements survive for a fresh pass."""
        _id(owner, "u")
        _id(meeting_id, "mt")
        removed = 0
        try:
            for found in self._meeting_query(owner, meeting_id, limit).stream():
                row = found.to_dict()
                if (
                    not isinstance(row, dict)
                    or row.get("org_id") != self.org
                    or row.get("owner") != owner
                    or not isinstance(row.get("source"), dict)
                    or row["source"].get("meeting_id") != meeting_id
                    or re.fullmatch(r"[0-9a-f]{64}", found.id) is None
                ):
                    raise _closed()
                try:
                    self.client.document(f"{self.collection}/{found.id}").delete(
                        option=self.client.write_option(last_update_time=found.update_time)
                    )
                    removed += 1
                except (FailedPrecondition, NotFound):
                    continue
        except Exception:
            raise _closed() from None
        return removed

    def erase_meeting_complete(self, owner: str, meeting_id: str, *, passes: int = 3, limit: int = 200) -> None:
        """Bounded drain after source tombstoning; completion requires a separate fresh indexed read."""
        if type(passes) is not int or not 1 <= passes <= 3:
            raise ValueError("invalid cleanup passes")
        for _ in range(passes):
            self.erase_meeting(owner, meeting_id, limit=limit)
            try:
                if next(iter(self._meeting_query(owner, meeting_id, 1).stream()), None) is None:
                    return
            except Exception:
                raise _closed() from None
        raise _closed()  # retry the already-deleted source; never claim partial cleanup complete
