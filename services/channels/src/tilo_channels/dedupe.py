"""The injected dedupe port shared by the Gmail push handler (FR-CHN-08) and any webhook (SEC-08)."""

from __future__ import annotations

from typing import Protocol


class DedupeStore(Protocol):
    def claim(self, key: str, ttl_s: float) -> bool:
        """Atomic set-if-absent: True for the first claimant of `key`, False afterwards (until ttl)."""
        ...
