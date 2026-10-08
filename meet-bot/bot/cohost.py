"""Future hook: co-host control through the Meet REST API. Interface only, nothing implemented.

Needs a Google Cloud project with OAuth consent and the Meet API enabled, which is out of scope for the prototype.
"""

from __future__ import annotations

from typing import Protocol


class CoHostManager(Protocol):
    async def add_cohost(self, email: str) -> None:
        """Make `email` a co-host of the current meeting."""
        ...


class NullCoHost:
    async def add_cohost(self, email: str) -> None:
        raise NotImplementedError("Co-host control is future work (Meet REST API).")
