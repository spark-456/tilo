"""tilo_channels.quiet_hours: per-user quiet hours notification filter (FR-HIL-13; PRD 10.2, 10.6, 13.1)."""

from __future__ import annotations

import copy
import datetime as dt
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

__all__ = [
    "ALWAYS_NOTIFY_TYPES",
    "DeliveryDecision",
    "NotificationGate",
    "PreferenceReader",
    "QuietHours",
    "is_quiet_hours",
    "parse_quiet_hours",
    "should_notify",
]

ALWAYS_NOTIFY_TYPES: frozenset[str] = frozenset({"gate", "blocked"})
_HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


class PreferenceReader(Protocol):
    def get(self, user_id: str) -> dict | None: ...


def _parse_hhmm(value: object) -> int:
    if not isinstance(value, str) or (m := _HHMM_RE.match(value.strip())) is None:
        raise ValueError(f"invalid HH:MM time: {value!r}")
    return int(m.group(1)) * 60 + int(m.group(2))


def _load_tz(tz_name: object) -> ZoneInfo:
    if not isinstance(tz_name, str) or not tz_name.strip():
        raise ValueError(f"invalid timezone: {tz_name!r}")
    try:
        return ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {tz_name!r}") from exc


def _to_utc_datetime(now: float | int | str | dt.datetime | None) -> dt.datetime:
    if now is None:
        return dt.datetime.now(dt.UTC)
    if isinstance(now, dt.datetime):
        return now.astimezone(dt.UTC) if now.tzinfo is not None else now.replace(tzinfo=dt.UTC)
    if isinstance(now, int | float):
        return dt.datetime.fromtimestamp(float(now), tz=dt.UTC)
    if isinstance(now, str):
        raw = now.strip()
        parsed = dt.datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        return parsed.astimezone(dt.UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)
    raise TypeError(f"unsupported timestamp type: {type(now).__name__}")


@dataclass(frozen=True)
class QuietHours:
    start: str
    end: str
    timezone: str = "UTC"

    def __post_init__(self) -> None:
        _parse_hhmm(self.start)
        _parse_hhmm(self.end)
        _load_tz(self.timezone)

    def is_active(self, now: float | int | str | dt.datetime | None = None) -> bool:
        start_min, end_min = _parse_hhmm(self.start), _parse_hhmm(self.end)
        if start_min == end_min:
            return False
        local_dt = _to_utc_datetime(now).astimezone(_load_tz(self.timezone))
        cur_min = local_dt.hour * 60 + local_dt.minute
        return (start_min <= cur_min < end_min) if start_min < end_min else (cur_min >= start_min or cur_min < end_min)


def parse_quiet_hours(prefs: Mapping[str, Any] | QuietHours | None) -> QuietHours | None:
    if isinstance(prefs, QuietHours):
        return prefs
    if not isinstance(prefs, Mapping):
        return None
    raw = prefs.get("quiet_hours")
    block = raw if isinstance(raw, Mapping) else (prefs if "start" in prefs and "end" in prefs else None)
    if not isinstance(block, Mapping) or block.get("enabled") is False:
        return None
    start, end = block.get("start"), block.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    tz = block.get("timezone") or block.get("time_zone") or prefs.get("timezone") or prefs.get("time_zone") or "UTC"
    try:
        return QuietHours(start=start, end=end, timezone=str(tz))
    except ValueError:
        return None


def is_quiet_hours(
    prefs: Mapping[str, Any] | QuietHours | None, *, now: float | int | str | dt.datetime | None = None
) -> bool:
    window = parse_quiet_hours(prefs)
    return window.is_active(now) if window is not None else False


def _notification_kind(item: Mapping[str, Any] | str) -> str:
    if isinstance(item, str):
        return item.strip().lower()
    if isinstance(item, Mapping):
        for key in ("rung", "severity", "kind", "type"):
            if isinstance(val := item.get(key), str) and val.strip():
                return val.strip().lower()
    return ""


def should_notify(
    item: Mapping[str, Any] | str,
    *,
    prefs: Mapping[str, Any] | QuietHours | None = None,
    now: float | int | str | dt.datetime | None = None,
) -> bool:
    kind = _notification_kind(item)
    return (kind in ALWAYS_NOTIFY_TYPES) if is_quiet_hours(prefs, now=now) else (kind not in ("info", "fyi"))


@dataclass(frozen=True)
class DeliveryDecision:
    notified: bool
    in_app: bool = True


class NotificationGate:
    def __init__(
        self,
        *,
        preferences: PreferenceReader | Mapping[str, dict] | None = None,
        clock: Callable[[], float | int | str | dt.datetime] | None = None,
        sender: Callable[[dict], None] | None = None,
    ) -> None:
        self._prefs, self._clock, self._sender = preferences, clock or (lambda: dt.datetime.now(dt.UTC)), sender
        self._in_app: dict[str, list[dict]] = {}
        self._lock = threading.Lock()

    def should_notify(
        self, user_id: str, item: Mapping[str, Any] | str, *, now: float | int | str | dt.datetime | None = None
    ) -> bool:
        prefs = self._prefs.get(user_id) if self._prefs is not None else None
        return should_notify(item, prefs=prefs, now=self._clock() if now is None else now)

    def deliver(self, user_id: str, item: dict) -> DeliveryDecision:
        stored, notify = copy.deepcopy(item), self.should_notify(user_id, item)
        with self._lock:
            self._in_app.setdefault(user_id, []).append(stored)
        if notify and self._sender is not None:
            self._sender(copy.deepcopy(stored))
        return DeliveryDecision(notified=notify, in_app=True)

    def in_app_items(self, user_id: str) -> list[dict]:
        with self._lock:
            return [copy.deepcopy(c) for c in self._in_app.get(user_id, ())]
