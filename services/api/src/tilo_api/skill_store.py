"""The taught-skill store (SKILLS-2, FR-SKL-04; contracts/taught_skill.schema.json, taught_skill.rules.md TS-01).

A repository of plain dicts that conform to the schema. A store never mutates what it is handed and returns copies.
`list_visible` is the owner's own skills plus every skill of the org whose scope is `team` and whose team is in the
caller's current teams; the caller works the teams out from the people record on every call. In memory only: the
Firestore store is `skill_firestore.py` (SKILLS-2b, BQ-SKILLS-1); `deps.get_skill_store` picks by env. Real runs,
ratings and fixes (FR-SKL-05, ADR-0037) are `skill_ledger.SkillLedger`, shared by both stores.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from tilo_api.skill_ledger import SkillLedger, Tx


class SkillStoreError(RuntimeError):
    """A store refused or failed; the message names no record text and no cause (the route says 503 `unavailable`)."""


class SkillStore(Protocol):
    def put(self, record: dict[str, Any]) -> None: ...
    def get(self, org: str, skill_id: str) -> dict[str, Any] | None: ...
    def list_for_owner(self, org: str, owner: str) -> list[dict[str, Any]]: ...
    def list_visible(self, org: str, user: str, team_ids: Iterable[str]) -> list[dict[str, Any]]: ...
    # FR-SKL-05/06 (SkillLedger): each write is atomic and raises `SkillRefused(reason)` before it writes anything.
    def start_real_run(
        self, org: str, skill_id: str, *, by: str, teams: Iterable[str], world_id: str, run_id: str, now: str
    ) -> dict[str, Any]: ...
    def finish_real_run(self, org: str, skill_id: str, run_id: str, *, outcome: str, at: str) -> dict[str, Any]: ...
    def record_rating(self, org: str, skill_id: str, rating: dict[str, Any]) -> dict[str, Any]: ...
    def apply_fix(self, org: str, skill_id: str, fix: dict[str, Any]) -> dict[str, Any]: ...
    def set_state(
        self, org: str, skill_id: str, change: str, *, by: str, threshold: int, now: str
    ) -> tuple[dict[str, Any], bool]: ...
    def get_real_run(self, org: str, skill_id: str, run_id: str) -> dict[str, Any] | None: ...
    def list_real_runs(self, org: str, skill_id: str) -> list[dict[str, Any]]: ...
    def list_ratings(self, org: str, skill_id: str) -> list[dict[str, Any]]: ...
    def list_fixes(self, org: str, skill_id: str) -> list[dict[str, Any]]: ...


def _path(org: str, skill_id: str) -> str:
    return f"orgs/{org}/taught_skills/{skill_id}"


class MemorySkillStore(SkillLedger):
    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}  # by Firestore path: skills and their subcollections
        self._lock = threading.RLock()

    def _under(self, path: str) -> list[dict[str, Any]]:
        prefix = path + "/"
        with self._lock:
            return [
                copy.deepcopy(d) for p, d in self._docs.items() if p.startswith(prefix) and "/" not in p[len(prefix) :]
            ]

    def _doc(self, path: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._docs.get(path)
            return None if found is None else copy.deepcopy(found)

    def _children(self, path: str) -> list[dict[str, Any]]:
        return self._under(path)

    def _atomic(self, work: Callable[[Tx], Any]) -> Any:
        with self._lock:
            tx = Tx(self._doc, lambda coll, field, value: [d for d in self._under(coll) if d.get(field) == value])
            out = work(tx)
            if any(kind == "create" and path in self._docs for kind, path, _ in tx.writes):
                raise SkillStoreError("the document exists")
            for _, path, doc in tx.writes:
                self._docs[path] = doc
            return out

    def put(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._docs[_path(record["org_id"], record["id"])] = copy.deepcopy(record)

    def get(self, org: str, skill_id: str) -> dict[str, Any] | None:
        return self._doc(_path(org, skill_id))

    def _skills(self, org: str) -> list[dict[str, Any]]:
        return self._under(f"orgs/{org}/taught_skills")

    def list_for_owner(self, org: str, owner: str) -> list[dict[str, Any]]:
        return [r for r in self._skills(org) if r["owner"] == owner]

    def list_visible(self, org: str, user: str, team_ids: Iterable[str]) -> list[dict[str, Any]]:
        teams = set(team_ids)
        return [
            r
            for r in self._skills(org)
            if r["owner"] == user or (r["scope"]["kind"] == "team" and r["scope"]["team"] in teams)
        ]
