"""Reading one people record as the signed-in person (API_PPL_11b.md section 4, BQ-PPL11B-12).

The visibility oracle is `tilo_people.access`; this module only loads what `read` needs around a record (its
source meeting, the released work item of a calendar proposal, the owner of an outside source) from the stores,
never from the request, and hands it canonical plain data. A refusal, a missing record and a malformed id all
give None: callers cannot tell them apart. Any failure to load or to decide is a refusal (fail closed).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

import tilo_people.access as access
from tilo_people.stores import PeopleStores
from tilo_policy.schemas import conforms

_STORES = {
    "work_item": "work_items",
    "pinboard_item": "pins",
    "calendar_entry": "calendar",
    "meeting": "meetings",
    "person": "persons",
}
_ID_SCHEMAS = {
    "work_item": "work_item_id",
    "pinboard_item": "pin_id",
    "calendar_entry": "calendar_entry_id",
    "meeting": "meeting_id",
    "person": "user_id",
}
_OUTSIDE_SOURCES = frozenset({"mail", "request", "call", "google"})
_OUTSIDE_FROM = frozenset({"request", "mail"})


class SourceOwners(Protocol):
    """PPL-10 "What callers must know": the owner of a mail, request, call or Google source comes from the
    source's own store, never from the record that cites it."""

    def owner_of(self, org_id: str, record_kind: str, record: Mapping[str, Any]) -> str | None: ...


class NoSourceOwners:
    """Production default until PPL-31 and PPL-11a supply one: always None, so such records are refused."""

    def owner_of(self, org_id: str, record_kind: str, record: Mapping[str, Any]) -> str | None:
        return None


def plain(value: Any) -> Any:
    """A JSON round trip: exact str, dict, list, int, float, bool and None, whatever subclasses a store returned."""
    return json.loads(json.dumps(value, allow_nan=False))


def _source(record: Mapping[str, Any]) -> Mapping[str, Any]:
    source = record.get("source")
    return source if isinstance(source, Mapping) else {}


def _tilo_made(record: Mapping[str, Any]) -> bool:
    made = record.get("created_by")
    return isinstance(made, Mapping) and made.get("by") == "tilo"


def _meeting_id(kind: str, record: Mapping[str, Any]) -> str | None:
    if not _tilo_made(record) or kind not in ("work_item", "pinboard_item", "calendar_entry"):
        return None
    source = _source(record)
    if kind == "calendar_entry":
        named = source.get("kind") == "tilo" and source.get("from") in ("meeting", "transcript")
    else:
        named = source.get("kind") == "meeting"
    ref = source.get("ref")
    if not named or not isinstance(ref, str):
        return None
    found = ref.split("#")[0]
    return found if conforms("common.schema.json#/$defs/meeting_id", found) else None


def _released_item(people: PeopleStores, org_id: str, entry: Mapping[str, Any]) -> Any:
    source = _source(entry)
    ref = source.get("ref")
    if not (_tilo_made(entry) and source.get("kind") == "tilo" and isinstance(ref, str) and "#" in ref):
        return None
    owned = people.work_items.list(org_id, "owner", entry["owner"])
    matches = [s.record for s in owned if _source(s.record).get("ref") == ref]
    return plain(matches[0]) if len(matches) == 1 else None


def _needs_source_owner(record: Mapping[str, Any]) -> bool:
    source = _source(record)
    return _tilo_made(record) and (
        source.get("kind") in _OUTSIDE_SOURCES or (source.get("kind") == "tilo" and source.get("from") in _OUTSIDE_FROM)
    )


def read_as(
    people: PeopleStores,
    directory: Any,
    *,
    actor: str,
    org_id: str,
    record_kind: str,
    record_id: str,
    now: str,
    source_owners: SourceOwners,
) -> dict[str, Any] | None:
    """The full view of one record of `org_id` for `actor`, or None (refused, missing, malformed or unreadable)."""
    try:
        if not all(isinstance(v, str) for v in (actor, org_id, record_kind, record_id, now)):
            return None
        if record_kind not in _STORES or not conforms(
            f"common.schema.json#/$defs/{_ID_SCHEMAS[record_kind]}", record_id
        ):
            return None
        actor, org_id, record_kind, record_id, now = (plain(v) for v in (actor, org_id, record_kind, record_id, now))
        stored = getattr(people, _STORES[record_kind]).get(org_id, record_id)
        if stored is None:
            return None
        record = plain(stored.record)
        if record.get("id") != record_id:  # the oracle itself refuses a record of another org than the actor's
            return None
        meeting = None
        meeting_id = _meeting_id(record_kind, record)
        if meeting_id is not None:
            found = people.meetings.get(org_id, meeting_id)
            meeting = None if found is None else plain(found.record)
        work_item = _released_item(people, org_id, record) if record_kind == "calendar_entry" else None
        owner = source_owners.owner_of(org_id, record_kind, record) if _needs_source_owner(record) else None
        request = access.AccessRequest(
            actor=actor,
            action="read_full",
            record_kind=record_kind,
            record=record,
            now=now,
            meeting=meeting,
            work_item=work_item,
            source_owner=plain(owner) if isinstance(owner, str) else None,
        )
        return access.read(request, directory)
    except Exception:
        return None
