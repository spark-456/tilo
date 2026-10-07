"""What the panel may name (API_PPL_11b.md section 4, PE-11, PE-26, PE-27, BQ-PPL11B-14). People records go through
the PPL-10 oracle as the signed-in person; a world is the person's only when they own it; cards and mail are
nameable only as rows of the plate built in this request. A refused id and an unknown id are the same answer."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.assistant.config import AssistantConfig
from tilo_api.people_access import SourceOwners, read_as
from tilo_api.people_vet import decide_as

_PEOPLE_KINDS = ("work_item", "pinboard_item", "calendar_entry", "meeting", "person")
_ALLOWED_PEOPLE = ("work_item", "pinboard_item", "calendar_entry", "meeting")
_SHAPES = (
    ("work_item", "work_item_id"),
    ("pinboard_item", "pin_id"),
    ("calendar_entry", "calendar_entry_id"),
    ("meeting", "meeting_id"),
    ("world", "world_id"),
    ("card", "ulid"),
)
_PATH_KINDS = ("world", "meetings")  # /world/<id> and /meetings/<id> carry the selected record


@dataclass(frozen=True)
class Ref:
    kind: str
    id: str

    def json(self) -> dict[str, str]:
        return {"kind": self.kind, "id": self.id}


def _plain(ref: Ref) -> bool:
    return type(ref.kind) is str and type(ref.id) is str


class RefGate:
    def __init__(
        self,
        *,
        user: str,
        org_id: str,
        now: str,
        store: deps.Store,
        people: PeopleStores,
        directory: Directory,
        source_owners: SourceOwners,
        plate_refs: frozenset[Ref],
    ) -> None:
        self._user, self._org, self._now = user, org_id, now
        self._store, self._people, self._directory, self._owners = store, people, directory, source_owners
        self._plate_refs = plate_refs
        self._seen: dict[tuple[str, str], Mapping[str, Any] | None] = {}

    def record(self, ref: Ref) -> Mapping[str, Any] | None:
        """The full view of a people record for the signed-in person (memoised for the request), else None."""
        if not _plain(ref) or ref.kind not in _PEOPLE_KINDS:
            return None
        key = (ref.kind, ref.id)
        if key not in self._seen:
            self._seen[key] = read_as(
                self._people,
                self._directory,
                actor=self._user,
                org_id=self._org,
                record_kind=ref.kind,
                record_id=ref.id,
                now=self._now,
                source_owners=self._owners,
            )
        return self._seen[key]

    def stored(self, ref: Ref, action: str) -> Mapping[str, Any] | None:
        """FR-PA-10: the work item as stored now, only when `decide` lets the signed-in person do `action` to it."""
        if ref.kind != "work_item" or not _plain(ref):
            return None
        return decide_as(
            self._people,
            self._directory,
            actor=self._user,
            org_id=self._org,
            record_id=ref.id,
            action=action,
            now=self._now,
            source_owners=self._owners,
        )

    def allows(self, ref: Ref) -> bool:
        try:
            if not _plain(ref):
                return False
            if ref.kind in _ALLOWED_PEOPLE:
                return self.record(ref) is not None
            if ref.kind == "world":
                world = self._store.worlds.get(ref.id)
                return isinstance(world, deps.WorldRecord) and world.owner == self._user  # PE-27
            if ref.kind in ("card", "mail"):
                return ref in self._plate_refs
        except Exception:
            return False
        return False

    def context_ref(self, record: str | None, path: str) -> Ref | None:
        """The first candidate the gate admits: the selected `record`, then the id in /world/<id> or /meetings/<id>."""
        candidates = [record]
        parts = path.split("/") if isinstance(path, str) else []
        if len(parts) >= 3 and parts[0] == "" and parts[1] in _PATH_KINDS:
            candidates.append(parts[2])
        for candidate in candidates:
            ref = _shape(candidate)
            if ref is not None and self.allows(ref):
                return ref
        return None


def _shape(candidate: Any) -> Ref | None:
    if type(candidate) is not str:
        return None
    for kind, definition in _SHAPES:
        if conforms(f"common.schema.json#/$defs/{definition}", candidate):
            return Ref(kind, candidate)
    return None


def screen_of(path: str, config: AssistantConfig) -> str | None:
    """The screen a web path belongs to: its first segment through config; /meetings/<id> is `meeting`."""
    parts = path.split("/")
    if len(parts) < 2 or parts[0] != "":
        return None
    if parts[1] == "meetings" and len(parts) > 2 and parts[2]:
        return "meeting"
    return config.screens.get(parts[1])
