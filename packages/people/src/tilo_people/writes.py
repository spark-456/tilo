"""Write checks for people records (PPL-10c; people.rules.md PE-02, PE-04, PE-07, PE-17, PE-19).

`check_write` answers one question: what is wrong with storing `after` for this request? `()` means store it.
A caller runs `decide`, builds `after` with stamps `{by: actor, at: now}` from the session and the server
clock, runs `check_write`, then stores with compare-and-set. Deterministic code only: no model, store, clock
or randomness; `now` is the only time. It fails closed (anything unknown or malformed is a refusal, never an
exception) and answers with problem codes only, never record text. See packages/people/tests/API.md section 4.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta
from typing import Any

from ._schema import valid
from .access import AccessRequest, decide
from .directory import Directory

WRITE_PROBLEMS = (
    "not_allowed",
    "unsupported",
    "schema",
    "identity",
    "immutable",
    "stamp",
    "transition",
    "history",
    "owner_not_member",
    "after_not_allowed",
    "snooze_range",
)
_WRITES = ("create", "mention", "edit", "confirm", "untag", "mark_done", "assign_membership", "set_org_role")
_MISSING = object()
_SNOOZE_MAX = timedelta(days=30)
# Written by the harness as a meeting runs, never by its creator: a new meeting holds none of them.
_MEETING_SERVER_FIELDS = (
    "transcript",
    "minutes",
    "minutes_confirmed_by",
    "ended_reason",
    "delete_transcript_after",
    "delete_minutes_after",
)

# What each (kind, action) may change; everything else on the record must stay as stored (`immutable`).
_MAY: dict[tuple[str, str], frozenset[str]] = {
    ("work_item", "edit"): frozenset({"title", "due", "due_text", "snoozed_until", "status", "history", "updated_at"}),
    ("work_item", "confirm"): frozenset({"status", "confirmed_by", "history", "updated_at"}),
    ("work_item", "mark_done"): frozenset({"status", "history", "updated_at"}),
    ("pinboard_item", "edit"): frozenset(
        {"title", "body", "kind", "url", "owner", "due", "status", "history", "updated_at"}
    ),
    ("pinboard_item", "confirm"): frozenset({"status", "confirmed_by", "history", "updated_at"}),
    ("calendar_entry", "edit"): frozenset({"title", "start", "end", "all_day", "share", "state", "updated_at"}),
    ("calendar_entry", "confirm"): frozenset({"state", "confirmed_by", "updated_at"}),
    ("meeting", "edit"): frozenset({"title", "series", "scheduled", "agenda", "attendees"}),
    ("meeting", "confirm"): frozenset({"minutes_confirmed_by"}),
    ("mention", "untag"): frozenset({"removed"}),
    ("person", "assign_membership"): frozenset({"memberships"}),
    ("person", "set_org_role"): frozenset({"org_role"}),
}
_GOOGLE_EDIT = frozenset({"share", "updated_at"})  # a Google-synced entry: its times are Google's (FR-CAL-04)


def check_write(request: AccessRequest, after: Mapping[str, Any], directory: Directory) -> tuple[str, ...]:
    """The problems with storing `after` for this request; () means store it. Sorted, unique, never raises."""
    try:
        return _check(request, after, directory)
    except Exception:
        return ("not_allowed",)


def _check(request: AccessRequest, after: Mapping[str, Any], directory: Directory) -> tuple[str, ...]:
    if decide(request, directory).allowed is not True:
        return ("not_allowed",)
    kind, action = request.record_kind, request.action
    if action not in _WRITES:  # a read or start_capture
        return ("unsupported",)
    if not valid(f"{kind}.schema.json", after):
        return ("schema",)
    if action in ("create", "mention"):
        found = _created(request, after, directory)
    elif (kind, action) in _MAY:
        found = _changed(request, after, directory)
    else:
        found = {"unsupported"}
    return tuple(sorted(found))


def _j(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _maker(actor: str, now: str) -> dict[str, str]:
    return {"by": "person" if actor.startswith("u_") else "tilo", "ref": actor, "at": now}


# ---------------------------------------------------------------------------------------------
# Creates: every stamp is the actor's at now, nothing comes from the body (PE-19)
# ---------------------------------------------------------------------------------------------
def _created(request: AccessRequest, after: Mapping[str, Any], directory: Directory) -> set[str]:
    if _j(after) != _j(request.record):
        return {"identity"}
    kind, actor, now = request.record_kind, request.actor, request.now
    stamp = {"by": actor, "at": now}
    found: set[str] = set()
    if kind == "person":
        if after["created_by"] != stamp or any(m["assigned_by"] != stamp for m in after["memberships"]):
            found.add("stamp")
    elif kind == "meeting":
        attestation = after["attestation"]
        if (
            after["created_at"] != now
            or attestation["by"] != actor
            or attestation["at"] > now
            or "world_id" in after
            or any(after[key] is not None for key in _MEETING_SERVER_FIELDS)
        ):
            found.add("stamp")
        if after["status"] != "scheduled":  # the initial state; the harness moves it on (BQ-PPL10-23)
            found.add("transition")
    elif kind == "mention":
        if after["added_by"] != _maker(actor, now) or after["removed"] is not None:
            found.add("stamp")
    else:  # work_item, pinboard_item, calendar_entry
        wrong = after["created_by"] != _maker(actor, now) or after["confirmed_by"] is not None
        wrong = wrong or after["updated_at"] != now or after.get("created_at", now) != now
        if kind == "work_item":
            assigner = after["assigned_by"]
            if after["created_by"]["by"] == "tilo":
                wrong = wrong or assigner is None or assigner["at"] != now
            else:
                wrong = wrong or (assigner is not None and assigner != stamp)
        if after["created_by"]["by"] == "person" and _claims_tilos_origin(kind, after.get("source")):
            wrong = True  # a person-made record cannot claim an origin that is Tilo's (PE-08)
        if kind == "work_item" and after["snoozed_until"] is not None and not _snooze_ok(now, after["snoozed_until"]):
            found.add("snooze_range")
        if kind == "pinboard_item" and not _owner_ok(after, directory, now):
            found.add("owner_not_member")
        if kind == "calendar_entry" and not _share_ok(after, directory, now):
            found.add("owner_not_member")
        if wrong:
            found.add("stamp")
        if kind != "calendar_entry":
            created = [{"at": now, "by": actor, "change": "created", "status": after["status"]}]
            if after["history"] != created:
                found.add("history")
    return found


# ---------------------------------------------------------------------------------------------
# Other writes: the row's MAY set, and the moves it allows
# ---------------------------------------------------------------------------------------------
def _changed(request: AccessRequest, after: Mapping[str, Any], directory: Directory) -> set[str]:
    kind, action, actor, now = request.record_kind, request.action, request.actor, request.now
    before = request.record
    if after["id"] != before["id"] or after["org_id"] != before["org_id"]:
        return {"identity"}
    may = _MAY[(kind, action)]
    if kind == "calendar_entry" and action == "edit" and before["source"]["kind"] == "google":
        may = _GOOGLE_EDIT
    found: set[str] = set()
    for key in set(before) | set(after):
        if key in may:
            continue
        if (key in before) != (key in after) or (key in before and _j(before[key]) != _j(after[key])):
            found.add("immutable")
    stamp = {"by": actor, "at": now}
    changes: Collection[str] | None = ()  # the history change names allowed; None: a bad move, not checked
    if "updated_at" in may and after["updated_at"] != now:
        found.add("stamp")

    if kind == "work_item":
        if action == "edit":
            same, reopened = (
                before["status"] == after["status"],
                (before["status"], after["status"]) == ("done", "open"),
            )
            changes = ("edited", "snoozed", "reassign_requested") if same else ("reopened",) if reopened else None
            if changes is None:
                found.add("transition")
            until = after["snoozed_until"]
            if _j(before["snoozed_until"]) != _j(until) and until is not None and not _snooze_ok(now, until):
                found.add("snooze_range")
        else:
            ok = (before["status"], after["status"]) == (
                ("proposed", "open") if action == "confirm" else ("open", "done")
            )
            changes = (("confirmed",) if action == "confirm" else ("done",)) if ok else None
            if not ok:
                found.add("transition")
            if action == "confirm" and after["confirmed_by"] != stamp:
                found.add("stamp")
    elif kind == "pinboard_item":
        old, new = before["status"], after["status"]
        if action == "confirm":
            changes = ("accepted",) if (old, new) == ("proposed", "active") else None
            if after["confirmed_by"] != stamp:
                found.add("stamp")
            if not _owner_ok(after, directory, now):
                found.add("owner_not_member")
        elif old == new:
            changes = ("owner_changed",) if _j(before["owner"]) != _j(after["owner"]) else ("edited", "owner_changed")
        elif new == "removed" and old in ("active", "proposed"):
            personal_tilo = after["created_by"]["by"] == "tilo" and after["scope"]["kind"] == "personal"
            changes = ("undone",) if personal_tilo else ("removed",)
        else:
            changes = None
        if changes is None:
            found.add("transition")
        if action == "edit" and not _owner_ok(after, directory, now):
            found.add("owner_not_member")
    elif kind == "calendar_entry":
        old, new = before["state"], after["state"]
        if (
            "state" in may
            and action == "edit"
            and (old != new and (old, new) not in (("proposed", "declined"), ("accepted", "cancelled")))
        ):
            found.add("transition")
        if action == "confirm":
            if (old, new) != ("proposed", "accepted"):
                found.add("transition")
            if after["confirmed_by"] != stamp:
                found.add("stamp")
    elif kind == "meeting" and action == "confirm":
        if before["minutes_confirmed_by"] is not None or after["status"] != "minuted":
            found.add("transition")
        if after["minutes_confirmed_by"] != stamp:
            found.add("stamp")
    elif kind == "mention":
        if after["removed"] != stamp:
            found.add("stamp")
    elif action == "assign_membership":
        old_entries = {_j(m) for m in before["memberships"]}
        if any(_j(m) not in old_entries and m["assigned_by"] != stamp for m in after["memberships"]):
            found.add("stamp")
    elif action == "set_org_role":  # roles are only ever promoted
        if (before["org_role"], after["org_role"]) != ("member", "owner"):
            found.add("transition")
    if kind in ("work_item", "pinboard_item") and not _history_ok(before, after, actor, now, changes):
        found.add("history")
    if action == "edit" and not decide(dataclasses.replace(request, record=after), directory).allowed:
        found.add("after_not_allowed")
    return found


def _history_ok(
    before: Mapping[str, Any], after: Mapping[str, Any], actor: str, now: str, changes: Collection[str] | None
) -> bool:
    """History keeps the old entries as a prefix and gains exactly one: now, by the actor, the item's new status,
    and (when the move itself is allowed) a change name that row lists."""
    old, new = before["history"], after["history"]
    if len(new) != len(old) + 1 or _j(new[:-1]) != _j(old):
        return False
    entry = new[-1]
    named = changes is None or entry["change"] in changes
    return named and (entry["at"], entry["by"], entry["status"]) == (now, actor, after["status"])


def _owner_ok(pin: Mapping[str, Any], directory: Directory, now: str) -> bool:
    """A team pin's responsible person is nobody or a member of its team, of its org, at the write (PE-02)."""
    owner, scope = pin["owner"], pin["scope"]
    if scope["kind"] != "team" or owner is None:
        return True
    person = directory.record(owner)
    return person is not None and person["org_id"] == pin["org_id"] and directory.is_member(owner, scope["team"], now)


def _claims_tilos_origin(kind: str, source: Mapping[str, Any] | None) -> bool:
    """Only Tilo's own origins: a Google or Tilo calendar source, a meeting source on a work item or pin. A
    person makes work items from mail, pinboard items and requests too (FR-PA-01, PE-08)."""
    source_kind = None if source is None else source.get("kind")
    return source_kind in (("google", "tilo") if kind == "calendar_entry" else ("meeting",))


def _share_ok(entry: Mapping[str, Any], directory: Directory, now: str) -> bool:
    """A shared entry's owner is a member of that team, of the entry's org (PE-04)."""
    share = entry["share"]
    if share is None:
        return True
    person = directory.record(entry["owner"])
    return (
        person is not None
        and person["org_id"] == entry["org_id"]
        and directory.is_member(entry["owner"], share["team"], now)
    )


def _snooze_ok(now: str, until: str) -> bool:
    try:
        stamp = "%Y-%m-%dT%H:%M:%S.%fZ"
        return timedelta(0) < datetime.strptime(until, stamp) - datetime.strptime(now, stamp) <= _SNOOZE_MAX
    except ValueError:
        return False
