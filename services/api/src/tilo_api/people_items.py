"""The work-item routes of the people API (PPL-11c S1 and S1b; people.rules.md PE-03, PE-07, PE-19, PE-29, PE-30,
API_PPL_11c.md section 2): list, get, edit, done, snooze, reopen, not-mine, put-back.

Reads go through `tilo_people.read`, writes through `decide`, then the record rebuilt from the stored one plus the
server clock and exactly one history entry, `check_write`, and one compare-and-set (`Writer.commit`). Authorisation
comes before the record's own schema check, so a refused request is the one 404 whatever the record would have become.
Only the caller's own record is read from the directory (by id); a list reads the owner index, never the org.
Closed bodies: nothing a request names (id, org, owner, source, status, due, history, a stamp) is ever used.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Annotated, Any

from pydantic import StringConstraints, model_validator
from tilo_people.access import AccessRequest, decide, read
from tilo_people.dates import resolve_due
from tilo_people.directory import Directory
from tilo_policy.schemas import conforms

from tilo_api.people_quotes import MAX_HISTORY
from tilo_api.people_writes import DUE_TEXT_MAX, Refusal, Text, Writer, _Closed

LIST_MAX = 200
LIST_STATUSES = ("open", "done", "dropped")  # never `proposed`: the assigner confirms it, the owner does not read it
_TS = "%Y-%m-%dT%H:%M:%S.%fZ"
_SNOOZE_MAX = timedelta(days=30)
_TS_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$"  # common#timestamp
Timestamp = Annotated[str, StringConstraints(pattern=_TS_PATTERN)]

Build = Callable[[dict[str, Any], Directory], tuple[dict[str, Any], str]]  # (changed fields, history change name)


class EditIn(_Closed):
    """A title, a due phrase or both; `due_text: null` clears the phrase and `due`. Nothing else is ever taken."""

    title: Text | None = None
    due_text: Text | None = None

    @model_validator(mode="after")
    def _names_a_field(self) -> EditIn:
        if not self.model_fields_set or ("title" in self.model_fields_set and self.title is None):
            raise ValueError("fields")
        return self


class SnoozeIn(_Closed):
    until: Timestamp


def _nf() -> Refusal:
    return Refusal(404, "not_found")  # the one body of every refused read or write


def _refused(problem: str = "transition") -> Refusal:
    return Refusal(409, "write_refused", code="write_refused", problems=[problem])


def _directory(w: Writer) -> Directory:
    """Only the caller's own record, read by id; a person with no record is refused like any other stranger."""
    me = w.stores.persons.get(w.org, w.actor)
    if me is None:
        raise _nf()
    return Directory.of([me.record])


def _meeting(w: Writer, item: dict[str, Any], cache: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The stored meeting (or its tombstone) a meeting-sourced item names, which `decide` needs for a Tilo-made item."""
    if item["source"]["kind"] != "meeting":
        return None
    meeting_id = (item["source"]["ref"] or "").partition("#")[0]
    if cache is not None and meeting_id in cache:
        return cache[meeting_id]  # type: ignore[no-any-return]
    found = w.stores.meetings.get(w.org, meeting_id) if meeting_id else None
    record = None if found is None else dict(found.record)
    if cache is not None:
        cache[meeting_id] = record
    return record


def list_items(w: Writer, status: str | None) -> dict[str, Any]:
    """The caller's own readable items (never `proposed`, never another person's), by due date (none last), creation
    and id; at most `LIST_MAX`. `status` is one of `LIST_STATUSES` or None (the route checks it)."""
    d, cache = _directory(w), dict[str, dict[str, Any] | None]()
    items: list[dict[str, Any]] = []
    wanted = LIST_STATUSES if status is None else (status,)
    for stored in w.stores.work_items.list(w.org, "owner", w.actor):
        rec = stored.record
        if rec["owner"] != w.actor or rec["status"] not in wanted or len(rec["history"]) > MAX_HISTORY:
            continue  # cheap checks first: an unreadable record never reaches `decide`
        meeting = _meeting(w, dict(rec), cache)
        got = read(AccessRequest(w.actor, "read_full", "work_item", rec, w.now, meeting=meeting), d)
        if got is not None:
            items.append(got)
    items.sort(key=lambda r: (r["due"] is None, r["due"] or "", r["created_at"], r["id"]))
    return {"items": items[:LIST_MAX], "truncated": len(items) > LIST_MAX}


def get_item(w: Writer, item_id: str) -> dict[str, Any]:
    """The owner reads the full record, the assigner of an item that is no longer `proposed` its status view (PE-03)."""
    d, stored = _directory(w), w.stores.work_items.get(w.org, item_id)
    if stored is None or len(stored.record["history"]) > MAX_HISTORY:
        raise _nf()
    item = dict(stored.record)
    for action in ("read_full", "read_status"):
        got = read(AccessRequest(w.actor, action, "work_item", item, w.now, meeting=_meeting(w, item)), d)
        if got is not None:
            return got
    raise _nf()


def change_item(w: Writer, item_id: str, access: str, build: Build) -> dict[str, Any]:
    """`decide` on the stored record first (a refusal is the 404), then the rebuilt record: the stored one plus the
    named changes, `updated_at` = now and one history entry by the caller at now; `check_write`; one compare-and-set."""
    d, stored = _directory(w), w.stores.work_items.get(w.org, item_id)
    if stored is None or len(stored.record["history"]) > MAX_HISTORY:
        raise _nf()
    item = dict(stored.record)
    request = AccessRequest(w.actor, access, "work_item", item, w.now, meeting=_meeting(w, item))
    if not decide(request, d).allowed:
        raise _nf()
    changes, change = build(item, d)
    status = changes.get("status", item["status"])
    entry = {"at": w.now, "by": w.actor, "change": change, "status": status}
    after = {**item, **changes, "updated_at": w.now, "history": [*item["history"], entry]}
    if not conforms("work_item.schema.json", after):
        raise Refusal(422, "invalid_record")  # the caller's own text or numbers; authorisation has already passed
    w.commit(request, after, w.stores.work_items, d, _nf(), version=stored.version)
    return after


def edit_item(w: Writer, item_id: str, body: EditIn) -> dict[str, Any]:
    def build(item: dict[str, Any], d: Directory) -> tuple[dict[str, Any], str]:
        changes: dict[str, Any] = {}
        if body.title is not None:
            changes["title"] = w.text(body.title)
        if "due_text" in body.model_fields_set:
            text = None if body.due_text is None else w.text(body.due_text)
            if text is not None and len(text) > DUE_TEXT_MAX:
                raise Refusal(422, "invalid_record")  # never a silent null: the phrase is too long
            me = d.record(w.actor)
            due = resolve_due(text, meeting_at=w.now, time_zone=me["time_zone"] if me else "UTC")
            changes.update(due=due.due, due_text=due.due_text)
        return changes, "edited"

    return change_item(w, item_id, "edit", build)


def done_item(w: Writer, item_id: str) -> dict[str, Any]:
    return change_item(w, item_id, "mark_done", lambda item, d: ({"status": "done"}, "done"))


def reopen_item(w: Writer, item_id: str) -> dict[str, Any]:
    def build(item: dict[str, Any], d: Directory) -> tuple[dict[str, Any], str]:
        if item["status"] != "done":
            raise _refused()
        return {"status": "open"}, "reopened"

    return change_item(w, item_id, "edit", build)


def _in_window(now: str, until: str) -> bool:
    """`now` < `until` <= `now` + 30 days (PE-19); `check_write` asks only when the date changes, this always does."""
    try:
        return timedelta(0) < datetime.strptime(until, _TS) - datetime.strptime(now, _TS) <= _SNOOZE_MAX
    except ValueError:
        return False


def snooze_item(w: Writer, item_id: str, body: SnoozeIn) -> dict[str, Any]:
    def build(item: dict[str, Any], d: Directory) -> tuple[dict[str, Any], str]:
        if item["status"] != "open":
            raise _refused()
        if not _in_window(w.now, body.until):
            raise _refused("snooze_range")
        return {"snoozed_until": body.until}, "snoozed"

    return change_item(w, item_id, "edit", build)


def _asked(item: dict[str, Any]) -> bool:
    return bool(item["history"][-1]["change"] == "reassign_requested")


def not_mine(w: Writer, item_id: str) -> dict[str, Any]:
    """Ask the assigner to reassign: only an open item someone else assigned, not already asked (PE-29)."""

    def build(item: dict[str, Any], d: Directory) -> tuple[dict[str, Any], str]:
        assigner = item["assigned_by"]
        if item["status"] != "open" or assigner is None or assigner["by"] == w.actor or _asked(item):
            raise _refused()
        return {}, "reassign_requested"

    return change_item(w, item_id, "edit", build)


def put_back(w: Writer, item_id: str) -> dict[str, Any]:
    """Release a parked item: an asked one is released (asked wins over snoozed, as on the plate), else the snooze is
    cleared. A done item is put back with reopen; anything else is not parked."""

    def build(item: dict[str, Any], d: Directory) -> tuple[dict[str, Any], str]:
        snoozed = (item["snoozed_until"] or "") > w.now
        if item["status"] != "open" or not (_asked(item) or snoozed):
            raise _refused()
        return ({} if _asked(item) else {"snoozed_until": None}), "edited"

    return change_item(w, item_id, "edit", build)
