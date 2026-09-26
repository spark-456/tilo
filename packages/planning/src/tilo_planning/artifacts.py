"""Versioned artifact store with an origin record per version (FR-INT-02, PRD 13.3).

In memory until the Firestore/GCS store lands. A put with bytes identical to the latest version
returns that version; changed bytes make the next version. Each version records its safety screen
(`clean`, `flagged` with a reason, or `unscreened`), so a later reader (policy engine, OB-05) never
takes an unscreened or flagged file for a clean one.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """ULID: 48-bit millisecond time and 80 random bits in Crockford base32 (26 characters)."""
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(_CROCKFORD[(n >> (5 * i)) & 31] for i in range(25, -1, -1))


@dataclass(frozen=True)
class StoredArtifact:
    artifact_id: str
    version: int
    filename: str
    content: bytes
    content_type: str | None
    origin: dict[str, Any]
    screening: str = "unscreened"  # "clean" | "flagged" | "unscreened"
    screening_reason: str | None = None


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._versions: dict[str, list[StoredArtifact]] = {}
        self._lock = threading.Lock()

    def put(
        self,
        *,
        artifact_id: str | None,
        filename: str,
        content: bytes,
        content_type: str | None,
        task_id: str,
        received_at: str,
        screening: str = "unscreened",
        screening_reason: str | None = None,
    ) -> StoredArtifact:
        sha256 = hashlib.sha256(content).hexdigest()
        with self._lock:
            artifact_id = artifact_id or f"art_{new_ulid()}"
            versions = self._versions.setdefault(artifact_id, [])
            if versions and versions[-1].origin["sha256"] == sha256:
                return versions[-1]
            origin = {
                "source": "upload",
                "filename": filename,
                "sha256": sha256,
                "received_at": received_at,
                "task_id": task_id,
            }
            stored = StoredArtifact(
                artifact_id, len(versions) + 1, filename, content, content_type, origin, screening, screening_reason
            )
            versions.append(stored)
            return stored

    def get(self, artifact_id: str, version: int | None = None) -> StoredArtifact:
        versions = self._versions[artifact_id]
        if version is None:
            return versions[-1]
        if not 1 <= version <= len(versions):
            raise KeyError(f"{artifact_id} has no version {version}")
        return versions[version - 1]

    def list_ids(self) -> list[str]:
        return list(self._versions)
