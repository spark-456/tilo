"""tilo_channels.nudges: proactive panel nudges (FR-PA-15; FR-PA-05, PE-12, PRD 10.2, 8.3).

The reminder sweeper offers a `Nudge` (a person, a work item id and a rule from a closed list). `NudgeGate` decides in
code, never with a model, whether it is raised now: only inside the person's reminder window (`working_window` of
config/personal.yaml, 09:00 to 18:00 Asia/Kolkata), at most `daily_cap` (default 5) per person per local day, once per
(item, rule, day). A raised nudge is one `alert.raised` part of severity `nudge` in the person's Desk world, handed to
the `emit` port: fixed template text, no title, address or link; the event carries ids only (PE-12). A person snoozes
it for an hour or until tomorrow; a snoozed nudge returns once, when its time has come and the window and cap allow.

No provider, model, network or clock read other than the injected one; nothing logs. `NudgeStore.update` is one
atomic read-modify-write per person, and the part id is derived from the nudge, so a retry after a failed commit
writes the same event (EV-10).
"""

from __future__ import annotations

import copy
import datetime as dt
import hashlib
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar
from zoneinfo import ZoneInfo

import yaml
from tilo_policy.schemas import conforms

__all__ = [
    "DEFAULT_DAILY_CAP",
    "RULES",
    "SNOOZES",
    "MemoryNudgeStore",
    "Nudge",
    "NudgeGate",
    "NudgeResult",
    "NudgeRules",
    "NudgeStore",
]

DEFAULT_DAILY_CAP = 5
MAX_DAILY_CAP = 50
RULES: dict[str, str] = {  # the rule names the sweeper may offer, and the one line each says (templates, no model)
    "due_24h": "A work item is due within 24 hours.",
    "overdue": "A work item is overdue.",
}
RETURNED = "A snoozed reminder is due again."
SNOOZES = ("hour", "tomorrow")
_CONFIG = Path(__file__).resolve().parents[4] / "config" / "personal.yaml"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ID = re.compile(r"[A-Za-z0-9_]{1,64}\Z")
_HM = re.compile(r"([01]\d|2[0-3]):([0-5]\d)\Z")
_KEEP_KEYS = 400
_KEEP_ALERTS = 200
T = TypeVar("T")


@dataclass(frozen=True)
class NudgeRules:
    """The window (local HH:MM, start inclusive, end exclusive), the person's default zone and the daily cap."""

    window_start: str = "09:00"
    window_end: str = "18:00"
    zone: str = "Asia/Kolkata"
    daily_cap: int = DEFAULT_DAILY_CAP

    def __post_init__(self) -> None:
        if not (_HM.match(self.window_start) and _HM.match(self.window_end)) or self.window_start >= self.window_end:
            raise ValueError("window must be local HH:MM with start before end")
        if type(self.daily_cap) is not int or not 1 <= self.daily_cap <= MAX_DAILY_CAP:
            raise ValueError(f"daily_cap must be 1 to {MAX_DAILY_CAP}")
        ZoneInfo(self.zone)

    @classmethod
    def load(cls, path: Path | None = None) -> NudgeRules:
        """`working_window` and the optional `nudges.daily_cap` of config/personal.yaml; other keys are not read."""
        raw = yaml.safe_load((path or _CONFIG).read_text(encoding="utf-8"))
        window, nudges = raw["working_window"], raw.get("nudges") or {}
        return cls(window["start"], window["end"], daily_cap=nudges.get("daily_cap", DEFAULT_DAILY_CAP))


@dataclass(frozen=True)
class Nudge:
    user_id: str
    item_id: str  # the work item's own id
    rule: str  # a key of RULES


@dataclass(frozen=True)
class NudgeResult:
    status: Literal["raised", "deferred", "snoozed", "refused"]
    reason: str | None = None  # outside_window, cap, duplicate, unknown_alert
    alert_id: str | None = None
    until: str | None = None  # a snooze's return time, a UTC contract timestamp


class NudgeStore(Protocol):
    def update(self, user_id: str, fn: Callable[[dict[str, Any]], T]) -> T:
        """Runs `fn` on the person's state atomically; the changes are kept only if `fn` returns."""
        ...


class MemoryNudgeStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users: dict[str, dict[str, Any]] = {}

    def update(self, user_id: str, fn: Callable[[dict[str, Any]], T]) -> T:
        with self._lock:
            work = copy.deepcopy(self._users.get(user_id, {}))
            out = fn(work)
            self._users[user_id] = work
            return out


def _stable_ulid(*key: str) -> str:
    n = int.from_bytes(hashlib.sha256("\x1f".join(key).encode()).digest(), "big") % 32**25
    body = []
    for _ in range(25):
        n, r = divmod(n, 32)
        body.append(_CROCKFORD[r])
    return "0" + "".join(reversed(body))


def _stamp(at: dt.datetime) -> str:
    ms = int(at.timestamp() * 1000)
    return dt.datetime.fromtimestamp(ms // 1000, dt.UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


def _minutes(hm: str) -> int:
    return int(hm[:2]) * 60 + int(hm[3:])


class NudgeGate:
    def __init__(
        self,
        *,
        rules: NudgeRules,
        store: NudgeStore,
        emit: Callable[[str, dict[str, Any]], None],
        zone_of: Callable[[str], str | None] | None = None,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self._rules, self._store, self._emit = rules, store, emit
        self._zone_of = zone_of or (lambda _user: None)
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def _local(self, user_id: str, now: dt.datetime | None) -> tuple[dt.datetime, str]:
        at = self._clock() if now is None else now
        if not isinstance(at, dt.datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("now must be an aware datetime")
        zone = self._zone_of(user_id) or self._rules.zone
        local = at.astimezone(ZoneInfo(zone))
        return local, local.date().isoformat()

    def _inside(self, local: dt.datetime) -> bool:
        minute = local.hour * 60 + local.minute
        return _minutes(self._rules.window_start) <= minute < _minutes(self._rules.window_end)

    def _raise(self, user_id: str, alert_id: str, part_id: str, summary: str) -> None:
        part: dict[str, Any] = {"id": part_id, "type": "alert.raised", "actor": "system", "target": user_id}
        part |= {"summary": summary, "severity": "nudge", "vis": [], "authz": None}
        part["data"] = {"alert_id": alert_id, "card_id": None}
        if not conforms("events/data/alert.raised.schema.json", part["data"]):
            raise ValueError("not a valid alert.raised")
        self._emit(user_id, part)

    def offer(self, nudge: Nudge, *, now: dt.datetime | None = None) -> NudgeResult:
        """Raises the nudge now or says why not. A refusal (outside the window, over the cap) records nothing, so the
        sweeper's next tick may offer it again; a raised one is never raised twice for (item, rule, day)."""
        if (
            not conforms("common.schema.json#/$defs/user_id", nudge.user_id)
            or type(nudge.item_id) is not str
            or not _ID.match(nudge.item_id)
            or nudge.rule not in RULES
        ):
            raise ValueError("not a nudge the sweeper may offer")
        local, day = self._local(nudge.user_id, now)
        if not self._inside(local):
            return NudgeResult("deferred", "outside_window")
        key = f"{nudge.item_id}:{nudge.rule}:{day}"

        def txn(state: dict[str, Any]) -> NudgeResult:
            days, keys, alerts = (
                state.setdefault("days", {}),
                state.setdefault("keys", []),
                state.setdefault("alerts", {}),
            )
            if key in keys:
                return NudgeResult("deferred", "duplicate")
            if days.get(day, 0) >= self._rules.daily_cap:
                return NudgeResult("deferred", "cap")
            alert_id = _stable_ulid(nudge.user_id, key)
            self._raise(nudge.user_id, alert_id, _stable_ulid(nudge.user_id, alert_id, "raised"), RULES[nudge.rule])
            days[day] = days.get(day, 0) + 1
            keys.append(key)
            del keys[:-_KEEP_KEYS]
            alerts[alert_id] = {"item": nudge.item_id, "rule": nudge.rule, "day": day, "gen": 0}
            for old in list(alerts)[:-_KEEP_ALERTS]:  # bounded: the panel only needs today's
                alerts.pop(old, None)
                state.get("snoozed", {}).pop(old, None)
            state["days"] = {d: n for d, n in days.items() if d >= day}  # only today's count can still matter
            return NudgeResult("raised", alert_id=alert_id)

        return self._store.update(nudge.user_id, txn)

    def snooze(self, user_id: str, alert_id: str, choice: str, *, now: dt.datetime | None = None) -> NudgeResult:
        """Snooze the person's own nudge for an hour or until the window opens tomorrow. It returns once."""
        if choice not in SNOOZES:
            raise ValueError("choice must be 'hour' or 'tomorrow'")
        local, _day = self._local(user_id, now)
        if choice == "hour":
            until = local.replace(microsecond=0) + dt.timedelta(hours=1)
        else:
            start = local.date() + dt.timedelta(days=1)
            hh, mm = divmod(_minutes(self._rules.window_start), 60)
            until = dt.datetime(start.year, start.month, start.day, hh, mm, tzinfo=local.tzinfo)
        until_stamp = _stamp(until)

        def txn(state: dict[str, Any]) -> NudgeResult:
            if alert_id not in state.get("alerts", {}):
                return NudgeResult("refused", "unknown_alert")
            state.setdefault("snoozed", {})[alert_id] = until_stamp
            return NudgeResult("snoozed", alert_id=alert_id, until=until_stamp)

        return self._store.update(user_id, txn)

    def release(self, user_id: str, *, now: dt.datetime | None = None) -> list[NudgeResult]:
        """Raises, once each, the person's snoozed nudges whose time has come, inside the window and under the
        cap; the rest stay snoozed (held, not dropped)."""
        local, day = self._local(user_id, now)
        if not self._inside(local):
            return []
        stamp = _stamp(local)

        def txn(state: dict[str, Any]) -> list[NudgeResult]:
            snoozed, days, back = state.get("snoozed", {}), state.setdefault("days", {}), list[NudgeResult]()
            for alert_id, until in sorted(snoozed.items(), key=lambda kv: (kv[1], kv[0])):  # earliest first
                if until > stamp or days.get(day, 0) >= self._rules.daily_cap:
                    continue
                record = state["alerts"][alert_id]
                gen = record["gen"] + 1
                part_id = _stable_ulid(user_id, alert_id, "returned", str(gen))
                self._raise(user_id, alert_id, part_id, RETURNED)
                record["gen"] = gen
                days[day] = days.get(day, 0) + 1
                back.append(NudgeResult("raised", alert_id=alert_id))
            for result in back:
                snoozed.pop(str(result.alert_id), None)  # returns once
            return back

        return self._store.update(user_id, txn)

    def item_of(self, user_id: str, alert_id: str) -> str | None:
        """The work item id a raised nudge is about, for the panel; None for another person's or an unknown alert."""
        return self._store.update(user_id, lambda state: (state.get("alerts", {}).get(alert_id) or {}).get("item"))

    def active(self, user_id: str, *, now: dt.datetime | None = None) -> list[dict[str, Any]]:
        """The person's nudges raised on their local day, newest first: `alert_id`, `rule`, the template `summary`
        and `snoozed_until` (None when not snoozed). Ids and fixed words only; the panel finds the item with
        `item_of`."""
        _local, day = self._local(user_id, now)

        def read(state: dict[str, Any]) -> list[dict[str, Any]]:
            snoozed = state.get("snoozed", {})
            found = [
                {
                    "alert_id": alert_id,
                    "rule": rec["rule"],
                    "summary": RULES[rec["rule"]],
                    "snoozed_until": snoozed.get(alert_id),
                }
                for alert_id, rec in state.get("alerts", {}).items()
                if rec.get("day") == day and rec.get("rule") in RULES
            ]
            return found[::-1]

        return self._store.update(user_id, read)
