"""The taught-skill store (SKILLS-2, FR-SKL-04; contracts/taught_skill.schema.json, taught_skill.rules.md TS-01).

A repository of plain dicts that conform to the schema. A store never mutates what it is handed and returns copies.
`list_visible` is the owner's own skills plus every skill of the org whose scope is `team` and whose team is in the
caller's current teams; the caller works the teams out from the people record on every call. In memory only: the
Firestore store is `skill_firestore.py` (SKILLS-2b, BQ-SKILLS-1); `deps.get_skill_store` picks by env.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterable
from typing import Any, Protocol


class SkillStoreError(RuntimeError):
    """A store refused or failed; the message names no record text and no cause (the route says 503 `unavailable`)."""


class SkillStore(Protocol):
    def put(self, record: dict[str, Any]) -> None: ...
    def get(self, org: str, skill_id: str) -> dict[str, Any] | None: ...
    def list_for_owner(self, org: str, owner: str) -> list[dict[str, Any]]: ...
    def list_visible(self, org: str, user: str, team_ids: Iterable[str]) -> list[dict[str, Any]]: ...


class MemorySkillStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._rows[(record["org_id"], record["id"])] = copy.deepcopy(record)

    def get(self, org: str, skill_id: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._rows.get((org, skill_id))
            return None if found is None else copy.deepcopy(found)

    def list_for_owner(self, org: str, owner: str) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(r) for (o, _), r in self._rows.items() if o == org and r["owner"] == owner]

    def list_visible(self, org: str, user: str, team_ids: Iterable[str]) -> list[dict[str, Any]]:
        teams = set(team_ids)
        with self._lock:
            return [
                copy.deepcopy(r)
                for (o, _), r in self._rows.items()
                if o == org and (r["owner"] == user or (r["scope"]["kind"] == "team" and r["scope"]["team"] in teams))
            ]
