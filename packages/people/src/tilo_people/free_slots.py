"""Free-slot search over a person's cached calendar (FR-CAL-07b-1; BQ-CAL07B-1).

Pure: no model, network, I/O or clock. `now` and `tz` are arguments, and so is the working window (the
caller reads `working_window` of config/personal.yaml and hands it in; `parse_working_window` checks it).
Busy time is the person's own `accepted` calendar_entry records and `free_busy` intervals of the person;
proposed, declined, cancelled and other people's entries never block. An all-day entry blocks its local
day (or its start to end when it has one); an entry without an end blocks `default_entry_min`. Slots are
whole-duration fits inside the working window, on working days, aligned to `step_min` of the local clock,
earliest first. Errors carry a reason code, never record text.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, time, timedelta
from itertools import islice
from typing import Any
from zoneinfo import ZoneInfo

from ._schema import is_timestamp, is_user_id
from .errors import PeopleInputError

MAX_HORIZON_DAYS = 14
MAX_ENTRIES = 2000
MAX_COUNT = 50
_HM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_ZONE = re.compile(r"(?:UTC|[A-Z][A-Za-z_+-]*(?:/[A-Za-z0-9_+-]+){1,2})")
_DAY = timedelta(days=1)


class FreeSlotError(PeopleInputError):
    """A malformed argument or entry; `reason` is a code, `str(e)` is the code only."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _int(value: Any, low: int, high: int, reason: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise FreeSlotError(reason)
    return value


def _minutes(value: Any) -> int:
    match = _HM.fullmatch(value) if type(value) is str else None
    if match is None:
        raise FreeSlotError("bad_window")
    return int(match[1]) * 60 + int(match[2])


def parse_working_window(raw: Any) -> tuple[str, str]:
    """`working_window` of config/personal.yaml ({start, end}, local HH:MM, start before end)."""
    if not isinstance(raw, Mapping) or _minutes(raw.get("start")) >= _minutes(raw.get("end")):
        raise FreeSlotError("bad_window")
    return raw["start"], raw["end"]


def _instant(value: Any, reason: str) -> datetime:
    if type(value) is not str or not is_timestamp(value):
        raise FreeSlotError(reason)
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise FreeSlotError(reason) from None
    if moment.tzinfo is None:
        raise FreeSlotError(reason)
    return moment.astimezone(UTC)


def _span(item: Any, owner: str, zone: ZoneInfo, default: timedelta) -> list[tuple[datetime, datetime]]:
    if not isinstance(item, Mapping):
        raise FreeSlotError("bad_entry")
    if "busy" in item:  # a free_busy record (PE-04): every interval is busy
        if item.get("user") != owner:
            return []
        rows = item["busy"]
        if not isinstance(rows, list) or len(rows) > MAX_ENTRIES:
            raise FreeSlotError("bad_entry")
        spans = [
            (_instant(r.get("start"), "bad_entry"), _instant(r.get("end"), "bad_entry"))
            for r in rows
            if isinstance(r, Mapping)
        ]
        if len(spans) != len(rows):
            raise FreeSlotError("bad_entry")
        return [s for s in spans if s[0] < s[1]]
    if type(item.get("owner")) is not str or type(item.get("state")) is not str:
        raise FreeSlotError("bad_entry")
    if item["owner"] != owner or item["state"] != "accepted":
        return []
    start = _instant(item.get("start"), "bad_entry")
    end = None if item.get("end") is None else _instant(item["end"], "bad_entry")
    if type(item.get("all_day")) is not bool:
        raise FreeSlotError("bad_entry")
    if item["all_day"] and (end is None or end <= start):
        day = start.astimezone(zone).date()
        return [(datetime.combine(day, time(0), tzinfo=zone), datetime.combine(day + _DAY, time(0), tzinfo=zone))]
    return [(start, end if end is not None and end > start else start + default)]


def _merge(spans: list[tuple[datetime, datetime]], buffer: timedelta) -> tuple[list[datetime], list[datetime]]:
    merged: list[list[datetime]] = []
    for a, b in sorted((a.astimezone(UTC) - buffer, b.astimezone(UTC) + buffer) for a, b in spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [m[0] for m in merged], [m[1] for m in merged]


def _ceil(moment: datetime, zone: ZoneInfo, step: timedelta) -> datetime:
    """Round up to the next multiple of `step` on the local clock."""
    local = moment.astimezone(zone)
    since = timedelta(hours=local.hour, minutes=local.minute, seconds=local.second, microseconds=local.microsecond)
    return moment if since % step == timedelta(0) else moment + (step - since % step)


def find_free_slots(
    entries: Iterable[Any],
    *,
    owner: str,
    now: str,
    tz: str,
    duration_min: int,
    working_window: tuple[str, str] = ("09:00", "18:00"),
    working_days: Iterable[int] = (0, 1, 2, 3, 4),
    not_before: str | None = None,
    not_after: str | None = None,
    count: int = 3,
    step_min: int = 15,
    buffer_min: int = 0,
    default_entry_min: int = 60,
    horizon_days: int = MAX_HORIZON_DAYS,
) -> tuple[str, ...]:
    """Up to `count` start times (UTC timestamps) where `duration_min` fits free, earliest first."""
    if type(owner) is not str or not is_user_id(owner):
        raise FreeSlotError("bad_owner")
    if type(tz) is not str or _ZONE.fullmatch(tz) is None:
        raise FreeSlotError("bad_time_zone")
    try:
        zone = ZoneInfo(tz)
    except Exception:
        raise FreeSlotError("bad_time_zone") from None
    if not isinstance(working_window, (tuple, list)) or len(working_window) != 2:
        raise FreeSlotError("bad_window")
    w_start, w_end = _minutes(working_window[0]), _minutes(working_window[1])
    if w_start >= w_end:
        raise FreeSlotError("bad_window")
    if type(duration_min) is not int or duration_min < 1:
        raise FreeSlotError("bad_duration")
    if duration_min > w_end - w_start:
        raise FreeSlotError("duration_too_long")
    days = frozenset(working_days)
    if not days or any(type(d) is not int or not 0 <= d <= 6 for d in days):
        raise FreeSlotError("bad_working_days")
    count = _int(count, 1, MAX_COUNT, "bad_count")
    step = timedelta(minutes=_int(step_min, 1, 240, "bad_step"))
    buffer = timedelta(minutes=_int(buffer_min, 0, 240, "bad_buffer"))
    default = timedelta(minutes=_int(default_entry_min, 1, 1440, "bad_default"))
    horizon = _int(horizon_days, 1, 3650, "bad_horizon")
    low = _instant(now, "bad_time")
    start_at = max(low, _instant(not_before, "bad_time")) if not_before is not None else low
    stop_at = low + timedelta(days=min(horizon, MAX_HORIZON_DAYS))
    if not_after is not None:
        stop_at = min(stop_at, _instant(not_after, "bad_time"))
    rows = list(islice(entries, MAX_ENTRIES + 1)) if isinstance(entries, Iterable) else None
    if rows is None:
        raise FreeSlotError("bad_entry")
    if len(rows) > MAX_ENTRIES:
        raise FreeSlotError("too_many_entries")
    spans = [s for item in rows for s in _span(item, owner, zone, default)]
    if len(spans) > MAX_ENTRIES:
        raise FreeSlotError("too_many_entries")
    starts, ends = _merge(spans, buffer)
    length = timedelta(minutes=duration_min)
    advance = -(-length // step) * step  # the next proposal starts after this one, on the grid
    found: list[str] = []
    day = start_at.astimezone(zone).date()
    last = stop_at.astimezone(zone).date()
    while day <= last and len(found) < count:
        if day.weekday() in days:
            opens = datetime.combine(day, time(w_start // 60, w_start % 60), tzinfo=zone).astimezone(UTC)
            closes = datetime.combine(day, time(w_end // 60, w_end % 60), tzinfo=zone).astimezone(UTC)
            cursor = _ceil(max(opens, start_at), zone, step)
            while cursor + length <= min(closes, stop_at) and len(found) < count:
                i = bisect_right(ends, cursor)
                if i < len(starts) and starts[i] < cursor + length:
                    cursor = _ceil(ends[i], zone, step)
                    continue
                found.append(cursor.strftime("%Y-%m-%dT%H:%M:%S.") + f"{cursor.microsecond // 1000:03d}Z")
                cursor += advance
        day += _DAY
    return tuple(found)
