"""ADR-0042 amendment 1 (owner 21 Oct, relayed): free times for a follow-up meeting, read-only, for the meeting owner.

Busy time, start and end only (never a title, attendee or link):
- the OWNER's own primary Google Calendar, one `read_events` through their own connection (ADR-0048), recorded as the
  WT-05 `data.transfer` in their own Desk world; all-day events never block a day;
- the owner's accepted Tilo calendar entries and their upcoming Tilo meetings;
- with `with_team`, each teammate's (members of the owner's teams, at most `MAX_TEAMMATES`) accepted Tilo calendar
  entries through PE-04 `read_busy`. A teammate's Google account is NEVER read: WT-01 lets a read touch only the
  person's own account, for that person's own feature.
`tilo_people.free_slots` finds the fits in the owner's working hours (09:00-18:00, Monday to Friday, their time zone);
the answer is the first free start on each of up to three days. Nothing is written to Google, nothing is sent."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tilo_people.access import AccessRequest, read
from tilo_people.free_slots import find_free_slots

from tilo_api import deps
from tilo_api.people_access import request_parts
from tilo_api.people_meetings import list_meetings
from tilo_api.people_pins import _Owners
from tilo_api.people_writes import Refusal, Writer

DEFAULT_ZONE = "Asia/Kolkata"
MAX_TEAMMATES, MAX_SLOTS = 8, 3
_UPCOMING = ("scheduled", "joining", "live")


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else None


def _zone(name: Any) -> str:
    try:
        ZoneInfo(name)
        return str(name)
    except Exception:
        return DEFAULT_ZONE


def find_times(
    w: Writer,
    owners: deps.SourceOwners,
    read_events: Callable[[str, dict[str, str]], Any],
    record: Callable[[str, str], None],
    *,
    minutes: int,
    days: int,
    with_team: bool,
) -> dict[str, Any]:
    """`read_events(user, args)`: the connectors read, for the OWNER only. `record(user, connected_at)`: WT-05."""
    d = w.org_directory()
    me = d.record(w.actor)
    if me is None:
        raise Refusal(404, "not_found")
    zone = _zone(me.get("time_zone"))
    now = datetime.fromisoformat(w.now.replace("Z", "+00:00"))
    window = {"start": _stamp(now), "end": _stamp(now + timedelta(days=days))}
    busy: list[dict[str, str]] = []

    def span(start: Any, end: Any) -> None:
        a, b = _instant(start), _instant(end)
        if a is not None and b is not None and a < b:
            busy.append({"start": _stamp(a), "end": _stamp(b)})

    google = "unavailable"
    try:
        answer = read_events(w.actor, window)
        if answer.outcome == "ok" and answer.result is not None and answer.connected_at is not None:
            record(w.actor, answer.connected_at)
            google = "ok"
            for event in answer.result.model_dump(mode="json")["events"]:
                if not event.get("all_day"):
                    span(event.get("start"), event.get("end"))
        elif answer.outcome in ("not_connected", "missing_scope"):
            google = "not_connected"
    except Exception:  # the connectors read failed: Tilo's own calendars still count
        google = "unavailable"

    for m in list_meetings(w)["items"]:
        if m.get("status") in _UPCOMING and isinstance(m.get("scheduled"), dict):
            span(m["scheduled"].get("start"), m["scheduled"].get("end"))
    teams = [m["team"] for m in me.get("memberships", []) if d.is_member(w.actor, m["team"], w.now)]
    mates = sorted({uid for uid in d.persons for t in teams if uid != w.actor and d.is_member(uid, t, w.now)})[
        :MAX_TEAMMATES
    ]
    for uid in [w.actor, *(mates if with_team else [])]:
        for stored in w.stores.calendar.list(w.org, "owner", uid):
            got = _busy(w, owners, stored.record, d)
            if got is not None:
                span(got.get("start"), got.get("end"))

    fits = find_free_slots(
        [{"user": w.actor, "busy": busy}],
        owner=w.actor,
        now=w.now,
        tz=zone,
        duration_min=minutes,
        count=50,
        horizon_days=days,
    )
    slots, seen = [], set()
    for start in fits:  # the first free start on each day, so the person gets a real choice
        day = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(ZoneInfo(zone)).date()
        if day not in seen:
            seen.add(day)
            slots.append(start)
    names = sorted(str(d.persons[uid].get("display_name") or "")[:80] for uid in mates) if with_team else []
    return {"slots": slots[:MAX_SLOTS], "zone": zone, "google": google, "teammates": names}


def _busy(w: Writer, owners: deps.SourceOwners, record: dict[str, Any], d: Any) -> dict[str, Any] | None:
    """PE-04 `read_busy` for the owner on one calendar entry: its start and end, or None."""
    if not isinstance(record, dict) or not isinstance(record.get("id"), str):
        return None
    try:
        parts = request_parts(
            w.stores,
            actor=w.actor,
            org_id=w.org,
            record_kind="calendar_entry",
            record_id=record["id"],
            now=w.now,
            source_owners=_Owners(owners),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    return None if parts is None else read(AccessRequest(action="read_busy", **parts), d)
