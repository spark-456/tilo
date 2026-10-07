"""Record stores, the meeting tombstone, calendar disconnect and person erasure (PPL-10d; API.md section 5).

The stores authorise nothing (callers run `decide` and `check_write` first). They key records by
`(org_id, id)`, validate each record against its kind's schema through `tilo_people._schema`, and update
only by compare-and-set. Errors and reprs name kinds, ids and versions, never record text.

`delete_meeting`, `disconnect_calendar` and `erase_person` are written against the `RecordStore` protocol
only, so a Firestore store gets them unchanged. No clock, logging or I/O happens here.
"""

from __future__ import annotations

import copy
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from tilo_people._schema import valid
from tilo_people.errors import (
    AlreadyExists,
    EmailTaken,
    LastPerson,
    NotFound,
    OrgAlreadyFounded,
    PeopleInputError,
    VersionConflict,
)

INDEXES: Mapping[str, tuple[str, ...]] = {
    "person": (),
    "meeting": ("owner",),
    "work_item": ("owner",),
    "pinboard_item": ("scope.user", "scope.team", "set_up_by"),
    "mention": ("pin_id", "user"),
    "calendar_entry": ("owner",),
}

_MISSING = object()
_SAFE_ID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_ATTEMPTS = 3


@dataclass(frozen=True)
class Stored:
    kind: str
    record: Mapping[str, Any] = field(repr=False)  # a deep copy
    version: int  # 1 on create, +1 per replace


class RecordStore(Protocol):
    """What PPL-11a/b implement on Firestore later."""

    kind: str

    def get(self, org_id: str, record_id: str) -> Stored | None: ...
    def create(self, record: Mapping[str, Any]) -> Stored: ...
    def replace(self, record: Mapping[str, Any], *, expected_version: int) -> Stored: ...
    def delete(self, org_id: str, record_id: str, *, expected_version: int) -> None: ...
    def list(self, org_id: str, field: str | None = None, value: str | None = None) -> tuple[Stored, ...]: ...


def _safe(value: Any) -> str:
    """An id for a message; anything that is not plainly an id is not echoed."""
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else "<malformed>"


def _at(record: Mapping[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


class MemoryStore:
    """A `RecordStore` for one kind of `INDEXES`, atomic per call under one lock. `MemoryStore("person")` is the person
    store, which also holds the address reservations and the founder marker (PPL-11c-FS); no other kind has those."""

    def __new__(cls, kind: str) -> MemoryStore:
        return super().__new__(_PersonMemoryStore if cls is MemoryStore and kind == "person" else cls)

    def __init__(self, kind: str) -> None:
        if not isinstance(kind, str) or kind not in INDEXES:
            raise PeopleInputError("unknown record kind")
        self.kind = kind
        self._schema = f"{kind}.schema.json"
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], tuple[int, dict[str, Any]]] = {}

    def __repr__(self) -> str:
        return f"MemoryStore(kind={self.kind!r})"

    def _checked(self, record: Any) -> tuple[str, str]:
        if not isinstance(record, Mapping) or not valid(self._schema, record):
            raise PeopleInputError(f"malformed {self.kind} record")
        return record["org_id"], record["id"]

    @staticmethod
    def _version(expected_version: Any) -> int:
        if type(expected_version) is not int:
            raise PeopleInputError("expected_version must be an int")
        return expected_version

    def get(self, org_id: str, record_id: str) -> Stored | None:
        if not isinstance(org_id, str) or not isinstance(record_id, str):
            return None
        with self._lock:
            row = self._rows.get((org_id, record_id))
            if row is None:
                return None
            return Stored(self.kind, copy.deepcopy(row[1]), row[0])

    def create(self, record: Mapping[str, Any]) -> Stored:
        key = self._checked(record)
        copied = copy.deepcopy(dict(record))
        with self._lock:
            if key in self._rows:
                raise AlreadyExists(f"AlreadyExists: {self.kind} {key[1]}")
            self._reserve(key, copied)
            self._rows[key] = (1, copied)
        return Stored(self.kind, copy.deepcopy(copied), 1)

    def replace(self, record: Mapping[str, Any], *, expected_version: int) -> Stored:
        key = self._checked(record)
        expected = self._version(expected_version)
        copied = copy.deepcopy(dict(record))
        with self._lock:
            row = self._rows.get(key)
            if row is None:
                raise NotFound(f"NotFound: {self.kind} {key[1]}")
            if row[0] != expected:
                raise VersionConflict(f"VersionConflict: {self.kind} {key[1]} expected {expected} current {row[0]}")
            self._release(key, row[1])
            try:
                self._reserve(key, copied)
            except EmailTaken:
                self._reserve(key, row[1])  # the old address is held again: a refused replace changes nothing
                raise
            self._rows[key] = (row[0] + 1, copied)
            version = row[0] + 1
        return Stored(self.kind, copy.deepcopy(copied), version)

    def delete(self, org_id: str, record_id: str, *, expected_version: int) -> None:
        self._delete(org_id, record_id, expected_version, keep_one=False)

    def _delete(self, org_id: str, record_id: str, expected_version: int, *, keep_one: bool) -> None:
        expected = self._version(expected_version)
        key = (org_id, record_id)
        with self._lock:
            row = self._rows.get(key) if isinstance(org_id, str) and isinstance(record_id, str) else None
            if row is None:
                raise NotFound(f"NotFound: {self.kind} {_safe(record_id)}")
            if row[0] != expected:
                raise VersionConflict(
                    f"VersionConflict: {self.kind} {_safe(record_id)} expected {expected} current {row[0]}"
                )
            if keep_one:
                self._refuse_sole(key)
            self._release(key, row[1])
            del self._rows[key]

    def _refuse_sole(self, key: tuple[str, str]) -> None:
        """Hook of the person store (`delete_not_last`); called under `_lock`."""

    def _reserve(self, key: tuple[str, str], record: Mapping[str, Any]) -> None:
        """Hook of the person store (an address reservation); called under `_lock`."""

    def _release(self, key: tuple[str, str], record: Mapping[str, Any]) -> None:
        """Hook of the person store; called under `_lock`."""

    def list(self, org_id: str, field: str | None = None, value: str | None = None) -> tuple[Stored, ...]:
        if field is not None and (not isinstance(field, str) or field not in INDEXES[self.kind]):
            raise PeopleInputError(f"{self.kind} has no such index")
        if field is not None and not isinstance(value, str):
            raise PeopleInputError("index value must be a string")
        if not isinstance(org_id, str):
            return ()
        with self._lock:
            rows = [(k[1], v) for k, v in self._rows.items() if k[0] == org_id]
            rows.sort(key=lambda item: item[0])
            return tuple(
                Stored(self.kind, copy.deepcopy(rec), version)
                for _, (version, rec) in rows
                if field is None or _at(rec, field) == value
            )


class _PersonMemoryStore(MemoryStore):
    """The person store: one reservation per person for its lower-cased address and the org's founder marker, both
    changed under `_lock`, in the same step as the record (the Firestore store does the same in a transaction)."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self._emails: dict[tuple[str, str], str] = {}
        self._founders: dict[str, str] = {}

    def _reserve(self, key: tuple[str, str], record: Mapping[str, Any]) -> None:
        """Holds the record's address for its person; `EmailTaken` if another person holds it."""
        slot = (key[0], str(record["email"]).lower())
        if self._emails.setdefault(slot, key[1]) != key[1]:
            raise EmailTaken(f"EmailTaken: person {key[1]}")

    def _release(self, key: tuple[str, str], record: Mapping[str, Any]) -> None:
        self._emails.pop((key[0], str(record["email"]).lower()), None)

    def create_founder(self, record: Mapping[str, Any]) -> Stored:
        """The founder marker, the person and its address, in one step. Refused `OrgAlreadyFounded` when the org has a
        marker or any person, then `AlreadyExists` (id), then `EmailTaken`; a refusal writes nothing."""
        key = self._checked(record)
        if record.get("org_role") != "owner":
            raise PeopleInputError("a founder is an owner")
        copied = copy.deepcopy(dict(record))
        with self._lock:
            if key[0] in self._founders or any(org == key[0] for org, _ in self._rows):
                raise OrgAlreadyFounded("OrgAlreadyFounded")
            if key in self._rows:
                raise AlreadyExists(f"AlreadyExists: person {key[1]}")
            self._reserve(key, copied)
            self._rows[key] = (1, copied)
            self._founders[key[0]] = key[1]
        return Stored(self.kind, copy.deepcopy(copied), 1)

    def founded(self, org_id: str) -> bool:
        """Is there a founder marker for the org (never removed, even when everyone is erased)."""
        with self._lock:
            return isinstance(org_id, str) and org_id in self._founders

    def delete_not_last(self, org_id: str, record_id: str, *, expected_version: int) -> None:
        """`delete`, but `LastPerson` (nothing changed) for the sole person of an org nobody founded; the check and the
        delete are one step under `_lock` (PPL-11c-FS FS-17)."""
        self._delete(org_id, record_id, expected_version, keep_one=True)

    def _refuse_sole(self, key: tuple[str, str]) -> None:
        if key[0] not in self._founders and not any(org == key[0] and rid != key[1] for org, rid in self._rows):
            raise LastPerson(f"LastPerson: person {_safe(key[1])}")


@dataclass(frozen=True)
class PeopleStores:
    persons: RecordStore
    meetings: RecordStore
    work_items: RecordStore
    pins: RecordStore
    mentions: RecordStore
    calendar: RecordStore

    @classmethod
    def in_memory(cls) -> PeopleStores:
        return cls(
            persons=MemoryStore("person"),
            meetings=MemoryStore("meeting"),
            work_items=MemoryStore("work_item"),
            pins=MemoryStore("pinboard_item"),
            mentions=MemoryStore("mention"),
            calendar=MemoryStore("calendar_entry"),
        )


def meeting_tombstone(meeting: Mapping[str, Any]) -> dict[str, Any]:
    """PE-19 tombstone, a schema-valid meeting (BQ-PPL10-2): identity kept, every bit of content dropped."""
    if not isinstance(meeting, Mapping) or not valid("meeting.schema.json", meeting):
        raise PeopleInputError("malformed meeting record")
    tomb: dict[str, Any] = {
        key: copy.deepcopy(meeting[key])
        for key in ("id", "org_id", "owner", "world_id", "attestation", "source", "ended_reason", "created_at")
        if key in meeting
    }
    tomb.update(
        status="deleted",
        title="Deleted meeting",
        series=None,
        scheduled=None,
        agenda=[],
        attendees=[],
        transcript=None,
        minutes=None,
        minutes_confirmed_by=None,
        delete_transcript_after=None,
        delete_minutes_after=None,
    )
    return tomb


def delete_meeting(stores: PeopleStores, org_id: str, meeting_id: str, *, expected_version: int) -> Stored:
    """Replaces the meeting with its tombstone (compare-and-set). What was made from it is not touched."""
    current = stores.meetings.get(org_id, meeting_id)
    if current is None:
        raise NotFound(f"NotFound: meeting {_safe(meeting_id)}")
    return stores.meetings.replace(meeting_tombstone(current.record), expected_version=expected_version)


def _delete_matching(
    store: RecordStore,
    org_id: str,
    record_id: str,
    wanted: Callable[[Mapping[str, Any]], bool],
    delete: Callable[..., None] | None = None,
) -> bool:
    """Deletes the record (with `delete`, default `store.delete`) when it still exists and `wanted`; a racing writer is
    retried, then reported."""
    for attempt in range(_ATTEMPTS):
        current = store.get(org_id, record_id)
        if current is None or not wanted(current.record):
            return False
        try:
            (delete or store.delete)(org_id, record_id, expected_version=current.version)
        except NotFound:
            return False
        except VersionConflict:
            if attempt == _ATTEMPTS - 1:
                raise
            continue
        return True
    return False


def _tombstone(store: RecordStore, org_id: str, meeting_id: str) -> bool:
    for attempt in range(_ATTEMPTS):
        current = store.get(org_id, meeting_id)
        if current is None or current.record.get("status") == "deleted":
            return False
        try:
            store.replace(meeting_tombstone(current.record), expected_version=current.version)
        except NotFound:
            return False
        except VersionConflict:
            if attempt == _ATTEMPTS - 1:
                raise
            continue
        return True
    return False


def _is_google(entry: Mapping[str, Any]) -> bool:
    source = entry.get("source")
    return isinstance(source, Mapping) and source.get("kind") == "google"


def disconnect_calendar(stores: PeopleStores, org_id: str, owner: str) -> int:
    """PE-13: deletes the owner's entries whose source.kind is "google"; returns the count."""
    count = 0
    for stored in stores.calendar.list(org_id, "owner", owner):
        if _is_google(stored.record):
            count += _delete_matching(stores.calendar, org_id, stored.record["id"], _is_google)
    return count


def _holds(index: str, value: str) -> Callable[[Mapping[str, Any]], bool]:
    def holds(record: Mapping[str, Any]) -> bool:
        return bool(_at(record, index) == value)

    return holds


def _always(record: Mapping[str, Any]) -> bool:
    return True


def _refuse_last_person(stores: PeopleStores, org_id: str, user: str) -> None:
    """BQ-PPL11C-16: the sole person of an org that was never founded is not erased (nothing is changed). A store with
    no `founded` (a bare `RecordStore`) counts as not founded."""
    everyone = stores.persons.list(org_id)
    if len(everyone) == 1 and everyone[0].record["id"] == user:
        founded = getattr(stores.persons, "founded", None)
        if founded is None or not founded(org_id):
            raise LastPerson(f"LastPerson: person {_safe(user)}")


def erase_person(stores: PeopleStores, org_id: str, user: str) -> dict[str, int]:
    """PE-16 (BQ-PPL10-8): tombstones their meetings, then deletes their work items, personal pins,
    mentions naming them, calendar entries and finally their person record. Idempotent."""
    counts = dict.fromkeys(("meeting", "work_item", "pinboard_item", "mention", "calendar_entry", "person"), 0)
    _refuse_last_person(stores, org_id, user)
    for stored in stores.meetings.list(org_id, "owner", user):
        counts["meeting"] += _tombstone(stores.meetings, org_id, stored.record["id"])
    plan = (
        ("work_item", stores.work_items, "owner"),
        ("pinboard_item", stores.pins, "scope.user"),
        ("mention", stores.mentions, "user"),
        ("calendar_entry", stores.calendar, "owner"),
    )
    for name, store, index in plan:
        for stored in store.list(org_id, index, user):
            counts[name] += _delete_matching(store, org_id, stored.record["id"], _holds(index, user))
    # the sole-person check is repeated inside the delete, atomically, by a store that has `delete_not_last` (FS-17)
    delete = getattr(stores.persons, "delete_not_last", None)
    counts["person"] += _delete_matching(stores.persons, org_id, user, _always, delete)
    return counts
