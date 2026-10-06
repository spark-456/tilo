"""CalendarSync: keep each person's cached Google calendar fresh, cheaply and only inside their working window
(FR-CAL-08, with the read path of FR-CAL-02). API: tests/API_FR_CAL_08.md.

`run_due()` is the poller (the Cloud Scheduler tick calls it, a later ticket). Per person it reads everything from
the stored `SyncState`: owner, org and world come from the connection `register` stored, never from a caller or
from Google. A run is incremental by sync token; it lists in full only when there is no token or Google answered
410 in that run. The working window is checked against the clock before every request and a run that finds it
closed commits nothing. Titles are untrusted: each new or changed one is screened once through the injected
`Screen` (a SafetyProvider fits; a model is never called), failing closed. The sync token is stored only sealed
by the Kms, bound to the person and connection. Nothing here logs; outcomes, events and errors carry no title,
token or address.
"""

from __future__ import annotations

import contextlib
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import yaml

from ._schema import calendar_entry_validator
from ._time import add_seconds, format_ts, parse_ts
from .adapters.calendar import CALENDAR_READONLY, NO_TITLE, CalendarEvent, EventPage
from .calendar_cache import CalendarConnection, CalendarStore, SyncState, entry_id
from .errors import (
    AdapterError,
    CalendarConfigError,
    CalendarSyncRefused,
    ProviderUnavailable,
    RateLimited,
    SyncTokenExpired,
)
from .registry import ConnectorRegistry, load_strict_yaml
from .tokens import ConnectionExpired, InsufficientScope, Kms, KmsError, NotConnected, TokenError

DEFAULT_PERSONAL_CONFIG = Path(__file__).resolve().parents[4] / "config" / "personal.yaml"
CONNECTOR_ID = "google_calendar"
SEAL_CONTEXT = b"tilo.calendar_sync.v1"
MAX_RETRY_AFTER_S = 86400
CLOCK_SKEW_S = 300  # a clock this far behind the last run is a jump back: the person is due again

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_HHMM = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")
_USER, _ORG, _WORLD = (re.compile(rf"{p}_[0-9A-Za-z_]{{1,48}}") for p in ("u", "org", "w"))
_ZONE = re.compile(r"(UTC|[A-Z][A-Za-z_+-]*(/[A-Za-z0-9_+-]+){1,2})")  # person.time_zone (max 64 characters)
_LIMITS = {  # calendar_sync keys and their inclusive ranges
    "poll_interval_s": (60, 86400),
    "past_days": (0, 31),
    "future_days": (1, 731),
    "max_pages": (1, 1_000_000),
    "backoff_base_s": (1, 3600),
    "backoff_max_s": (1, 86400),
}


# -- config --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkingWindow:
    start: time  # naive local wall time, minutes only
    end: time  # exclusive; start < end

    def contains(self, now: str, time_zone: str) -> bool:
        """start <= local wall time < end in `time_zone`; a zone ZoneInfo cannot load raises."""
        return self.start <= parse_ts(now).astimezone(ZoneInfo(time_zone)).time() < self.end


@dataclass(frozen=True)
class CalendarSyncConfig:
    window: WorkingWindow
    poll_interval_s: int
    past_days: int
    future_days: int
    max_pages: int
    backoff_base_s: int
    backoff_max_s: int
    page_size: int  # google_calendar limits.batch_size
    per_minute: int  # google_calendar limits.per_minute: requests per person in any 60 s


def _read_yaml(text: str) -> Any:
    """The one place this module parses YAML: the registry's strict loader (no aliases, merge keys or repeated keys)."""
    return load_strict_yaml(text)


def _int(value: Any, low: int, high: int, key: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise CalendarConfigError(f"{key}: must be an integer from {low} to {high}")
    return value


def _block(raw: Any, name: str, keys: set[str]) -> dict[str, Any]:
    block = raw.get(name) if isinstance(raw, dict) else None
    if not isinstance(block, dict) or set(block) != keys:
        raise CalendarConfigError(f"{name}: must be a mapping with exactly the keys {', '.join(sorted(keys))}")
    return block


def load_calendar_sync_config(
    path: str | Path = DEFAULT_PERSONAL_CONFIG, *, registry: ConnectorRegistry
) -> CalendarSyncConfig:
    """Refuses the whole file (and a google_calendar declaration that is not read-only) with a message that
    names a key, never a value. Other top-level keys belong to CC-PEOPLE-2 and are ignored."""
    try:
        raw = _read_yaml(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError) as exc:
        raise CalendarConfigError(f"personal config: not a readable UTF-8 YAML file ({type(exc).__name__})") from None
    window, sync = _block(raw, "working_window", {"start", "end"}), _block(raw, "calendar_sync", set(_LIMITS))
    clock = {}
    for key, value in window.items():
        if not isinstance(value, str) or not _HHMM.fullmatch(value):
            raise CalendarConfigError(f"working_window.{key}: must be a quoted HH:MM string")
        clock[key] = time(int(value[:2]), int(value[3:]))
    if clock["start"] >= clock["end"]:
        raise CalendarConfigError("working_window: start must be before end")
    numbers = {key: _int(sync[key], *_LIMITS[key], f"calendar_sync.{key}") for key in _LIMITS}
    if numbers["backoff_max_s"] < numbers["backoff_base_s"]:
        raise CalendarConfigError("calendar_sync.backoff_max_s: must not be below backoff_base_s")
    declared: dict[str, Any] = registry.get(CONNECTOR_ID) if CONNECTOR_ID in registry else {}
    action: dict[str, Any] = next((a for a in declared.get("actions", []) if a.get("id") == "read_events"), {})
    if declared.get("scopes") != {"read": [CALENDAR_READONLY]} or (
        action.get("capability"),
        action.get("gate_type"),
        action.get("risk_tier"),
        action.get("irreversible"),
    ) != ("read", "none", "T1", False):
        raise CalendarConfigError("google_calendar: must declare only calendar.readonly and an ungated T1 read_events")
    limits = declared.get("limits", {})
    page_size = _int(limits.get("batch_size"), 1, 2500, "google_calendar.limits.batch_size")
    per_minute = _int(limits.get("per_minute"), 1, 1_000_000, "google_calendar.limits.per_minute")
    if 2 * numbers["max_pages"] >= per_minute:
        raise CalendarConfigError("calendar_sync.max_pages: twice it must stay below the per_minute limit")
    return CalendarSyncConfig(
        WorkingWindow(clock["start"], clock["end"]), **numbers, page_size=page_size, per_minute=per_minute
    )


# -- the sync ------------------------------------------------------------------------------------------


class Screen(Protocol):  # a tilo_providers SafetyProvider fits
    def check(self, text: str) -> Mapping[str, Any]: ...


class EventSource(Protocol):  # CalendarAdapter.list_events
    def list_events(
        self,
        user_id: str,
        *,
        page_size: int,
        sync_token: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        page_token: str | None = None,
    ) -> EventPage: ...


@dataclass(frozen=True)
class SyncOutcome:
    user_id: str
    status: str  # "synced" | "skipped" | "aborted" | "failed" | "forgotten"
    reason: str | None = None
    kind: str | None = None  # "incremental" | "full" when synced
    changed: int = 0  # calendar.synced data.changed; 0 unless synced
    requests: int = 0  # list_events calls this run (a page answered 410 counts)
    screened: int = 0  # screen.check calls this run
    skipped: int = 0  # unusable items plus entries refused by the schema, this run
    emitted: bool = False  # calendar.synced was handed to emit and emit returned


@dataclass
class _Run:
    user_id: str
    zone: str
    now: str
    requests: int = 0
    screened: int = 0
    skipped: int = 0
    dead_token: bool = False  # Google answered 410: the stored token is gone, whatever else happens


class _Stop(Exception):
    """Ends one run: `aborted` records nothing, `failed` backs off."""

    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


class CalendarSync:
    def __init__(
        self,
        *,
        config: CalendarSyncConfig,
        events: EventSource,
        store: CalendarStore,
        kms: Kms,
        screen: Screen,
        zone_of: Callable[[str], str | None],
        clock: Callable[[], str],
        emit: Callable[[dict[str, Any]], None],
    ) -> None:
        self._cfg, self._events, self._store, self._kms, self._screen = config, events, store, kms, screen
        self._zone_of, self._clock, self._emit = zone_of, clock, emit
        self._mutex = threading.Lock()  # guards the two tables below
        self._locks: dict[str, threading.Lock] = {}  # one run per person on this instance
        self._log: dict[str, list[float]] = {}  # request times per person, for the per-minute cap

    def register(self, *, user_id: str, org_id: str, world_id: str) -> CalendarConnection:
        """Called by the connect flow after consent, with server-side ids. No Google call, no event."""
        for value, pattern in ((user_id, _USER), (org_id, _ORG), (world_id, _WORLD)):
            if not isinstance(value, str) or not pattern.fullmatch(value):
                raise CalendarSyncRefused("register: an id is not in its common pattern")
        now = self._clock()
        connection_id = "cc_" + "".join(secrets.choice(_CROCKFORD) for _ in range(26))
        conn = CalendarConnection(user_id, org_id, world_id, connection_id, now)
        stored = self._store.add(SyncState(conn, 0, None, now, None, 0)).connection
        if (stored.org_id, stored.world_id) != (org_id, world_id):
            raise CalendarSyncRefused("register: this person is already registered under another org or world")
        return stored

    def forget(self, user_id: str) -> None:
        """Disconnect or user deletion (PE-13, PE-16): the state, the token and the entries, together."""
        self._store.forget(user_id)
        with self._mutex:
            self._log.pop(user_id, None)

    def run_due(self) -> tuple[SyncOutcome, ...]:
        outcomes = []
        for user_id in self._store.user_ids():
            try:
                outcomes.append(self._run_one(user_id))
            except Exception:  # one person's error never stops the others
                outcomes.append(SyncOutcome(user_id, "failed", "error"))
        return tuple(outcomes)

    # -- one person ------------------------------------------------------------------------------------

    def _run_one(self, user_id: str) -> SyncOutcome:
        state = self._store.get(user_id)
        if state is None:
            return SyncOutcome(user_id, "skipped", "not_registered")
        now, zone = self._clock(), self._zone(user_id)
        if zone is None:
            return SyncOutcome(user_id, "skipped", "no_time_zone")
        if not self._cfg.window.contains(now, zone):
            return SyncOutcome(user_id, "skipped", "outside_window")
        jumped_back = state.last_run_at is not None and now < add_seconds(state.last_run_at, -CLOCK_SKEW_S)
        if now < state.next_due_at and not jumped_back:
            return SyncOutcome(user_id, "skipped", "backing_off" if state.failures else "not_due")
        with self._mutex:
            lock = self._locks.setdefault(user_id, threading.Lock())
        if not lock.acquire(blocking=False):
            return SyncOutcome(user_id, "skipped", "busy")
        try:
            return self._locked(_Run(user_id, zone, now))
        finally:
            lock.release()

    def _zone(self, user_id: str) -> str | None:
        try:
            zone = self._zone_of(user_id)
            if isinstance(zone, str) and len(zone) <= 64 and _ZONE.fullmatch(zone):
                ZoneInfo(zone)
                return zone
        except Exception:  # not in the zone database, or the person record could not be read
            pass
        return None

    def _locked(self, run: _Run) -> SyncOutcome:
        state = self._store.get(run.user_id)
        if state is None:
            return SyncOutcome(run.user_id, "skipped", "not_registered")
        conn = state.connection
        aad = SEAL_CONTEXT + b"\x00" + conn.user_id.encode() + b"\x00" + conn.connection_id.encode()
        try:
            kind, events, sync_token = self._fetch(run, self._unseal(state, aad))
            return self._commit(run, state, aad, kind, events, sync_token)
        except NotConnected:  # disconnected: forget the person (PE-13)
            self.forget(run.user_id)
            return SyncOutcome(run.user_id, "forgotten", "not_connected")
        except Exception as exc:  # a person's failure is recorded by reason only: never a message
            if isinstance(exc, _Stop) and exc.status == "aborted":
                return self._outcome(run, "aborted", exc.reason)
            reason, wait = self._classify(exc, state.failures + 1)
            now = self._clock()
            token = None if run.dead_token else state.sealed_token
            failed = SyncState(conn, state.generation + 1, token, add_seconds(now, wait), now, state.failures + 1)
            if not self._store.commit(state, failed, upserts=(), removals=()):
                return self._outcome(run, "aborted", "superseded")
            return self._outcome(run, "failed", reason)

    def _outcome(self, run: _Run, status: str, reason: str | None = None, **more: Any) -> SyncOutcome:
        return SyncOutcome(
            run.user_id, status, reason, requests=run.requests, screened=run.screened, skipped=run.skipped, **more
        )

    def _classify(self, exc: Exception, n: int) -> tuple[str, int]:
        """(reason, seconds until the next try) for the n-th failure in a row."""
        cfg = self._cfg
        backoff = min(cfg.backoff_base_s * 2 ** min(n - 1, 40), cfg.backoff_max_s)
        if isinstance(exc, _Stop):
            return exc.reason, backoff
        if isinstance(exc, RateLimited):
            return "rate_limited", min(MAX_RETRY_AFTER_S, max(backoff, exc.retry_after_s))
        if isinstance(exc, ConnectionExpired):
            return "connection_expired", cfg.backoff_max_s
        if isinstance(exc, InsufficientScope):
            return "missing_scope", cfg.backoff_max_s
        if isinstance(exc, ProviderUnavailable | TokenError):
            return "unavailable", backoff
        if isinstance(exc, AdapterError):
            return ("rejected" if exc.status is not None else "malformed"), backoff
        return "error", backoff

    # -- fetching --------------------------------------------------------------------------------------

    def _unseal(self, state: SyncState, aad: bytes) -> str | None:
        if state.sealed_token is None:
            return None
        try:
            return self._kms.decrypt(state.sealed_token, aad=aad).decode()
        except (KmsError, UnicodeDecodeError):
            raise _Stop("failed", "token_unreadable") from None  # the token is kept

    def _fetch(self, run: _Run, token: str | None) -> tuple[str, list[CalendarEvent], str]:
        """Incremental on a stored token; one full listing when there is none or Google answers 410."""
        if token is not None:
            try:
                return "incremental", *self._pages(run, {"sync_token": token})
            except SyncTokenExpired:
                run.dead_token = True  # what was staged is dropped; the same run lists in full
        now = parse_ts(run.now)
        bounds = {
            "time_min": format_ts(now - timedelta(days=self._cfg.past_days)),
            "time_max": format_ts(now + timedelta(days=self._cfg.future_days)),
        }
        return "full", *self._pages(run, bounds)

    def _pages(self, run: _Run, mode: dict[str, str]) -> tuple[list[CalendarEvent], str]:
        events: list[CalendarEvent] = []
        seen: set[str] = set()
        page_token: str | None = None
        run.skipped = 0
        for _ in range(self._cfg.max_pages):
            self._admit(run)
            page = self._events.list_events(run.user_id, page_size=self._cfg.page_size, page_token=page_token, **mode)
            events += page.events
            run.skipped += page.skipped
            if page.next_sync_token is not None:
                return events, page.next_sync_token
            page_token = page.next_page_token
            if page_token is None:
                raise _Stop("failed", "malformed")
            if page_token in seen:
                raise _Stop("failed", "page_loop")
            seen.add(page_token)
        raise _Stop("failed", "too_many_pages")

    def _admit(self, run: _Run) -> None:
        """Before every request: the window is still open and the person is under the per-minute cap."""
        now = self._clock()
        if not self._cfg.window.contains(now, run.zone):
            raise _Stop("aborted", "window_closed")
        second = parse_ts(now).timestamp()
        with self._mutex:
            recent = [t for t in self._log.get(run.user_id, []) if second - 60 < t <= second]
            if len(recent) >= self._cfg.per_minute:
                raise _Stop("failed", "local_rate_limit")
            self._log[run.user_id] = [*recent, second]
        run.requests += 1

    # -- the commit ------------------------------------------------------------------------------------

    def _commit(
        self, run: _Run, state: SyncState, aad: bytes, kind: str, events: list[CalendarEvent], sync_token: str
    ) -> SyncOutcome:
        conn, now = state.connection, self._clock()
        upserts, removals, changed = self._diff(run, conn, kind, events, now)
        sealed = self._kms.encrypt(sync_token.encode(), aad=aad)
        new = SyncState(conn, state.generation + 1, sealed, add_seconds(now, self._cfg.poll_interval_s), now, 0)
        if not self._store.commit(state, new, upserts=upserts, removals=removals):
            raise _Stop("aborted", "superseded")  # another instance committed first, or the person was forgotten
        emitted = False
        if kind == "full" or changed > 0:  # at most once per commit; a failed emit is never retried
            part = {
                "type": "calendar.synced",
                "authz": None,
                "data": {"kind": kind, "changed": changed},
                "user_id": conn.user_id,
                "world_id": conn.world_id,
                "key": f"{conn.connection_id}:{new.generation}",
            }
            with contextlib.suppress(Exception):
                self._emit(part)
                emitted = True
        return self._outcome(run, "synced", kind=kind, changed=changed, emitted=emitted)

    def _diff(
        self, run: _Run, conn: CalendarConnection, kind: str, events: list[CalendarEvent], now: str
    ) -> tuple[list[dict[str, Any]], list[str], int]:
        """The entries to write and the ids to remove, and how many entries changed (API doc, "Building the
        commit"). Evictions of entries behind the horizon are housekeeping, not changes."""
        cfg, zone, when = self._cfg, ZoneInfo(run.zone), parse_ts(now)
        low, high = format_ts(when - timedelta(days=cfg.past_days)), format_ts(when + timedelta(days=cfg.future_days))
        stored = {e["id"]: e for e in self._store.entries(conn.user_id)}
        kept: set[str] = set()
        gone: set[str] = set()
        upserts: list[dict[str, Any]] = []
        verdicts: dict[str, bool] = {}
        for event in {e.event_id: e for e in events}.values():  # the last copy of an id wins
            eid = entry_id(conn.user_id, event.event_id)
            try:
                span = None if event.removed else (_utc(event.start, event, zone), _utc(event.end, event, zone))
            except (OverflowError, ValueError):
                run.skipped, span = run.skipped + 1, None
            if span is None or span[1] < low or span[0] >= high:
                gone.add(eid)
                continue
            kept.add(eid)
            old = stored.get(eid)
            same = (event.title, span[0], span[1], event.all_day, event.attendee_count)
            if (
                old is not None
                and (old["title"], old["start"], old["end"], old["all_day"], old["attendee_count"]) == same
            ):
                continue  # not rewritten
            entry = {
                "id": eid,
                "org_id": conn.org_id,
                "owner": conn.user_id,
                "title": event.title,
                "start": span[0],
                "end": span[1],
                "all_day": event.all_day,
                "attendee_count": event.attendee_count,
                "source": {"kind": "google", "ref": event.event_id, "synced_at": now},
                "state": "accepted",
                "share": None,
                "created_by": {"by": "tilo", "ref": "system", "at": old["created_by"]["at"] if old else now},
                "confirmed_by": None,
                "flagged": old["flagged"]
                if old and old["title"] == event.title
                else self._flagged(run, event.title, verdicts),
                "updated_at": now,
            }
            if calendar_entry_validator().is_valid(entry):
                upserts.append(entry)
            else:
                run.skipped += 1
        if kind == "full":
            gone |= stored.keys() - kept  # deleted while the token was dead
        evicted = {i for i, e in stored.items() if e["end"] is not None and e["end"] < low}
        removed = ((gone & stored.keys()) - kept) | (evicted - kept)
        return upserts, sorted(removed), len(upserts) + len(((gone & stored.keys()) - evicted) - kept)

    def _flagged(self, run: _Run, title: str, verdicts: dict[str, bool]) -> bool:
        """One safety screen per distinct new or changed title; Tilo's own `(No title)` is not screened."""
        if title == NO_TITLE:
            return False
        if title not in verdicts:
            run.screened += 1
            try:
                verdict: Any = self._screen.check(title)
            except Exception:  # fail closed
                verdict = None
            verdicts[title] = not (isinstance(verdict, Mapping) and verdict.get("flagged") is False)
        return verdicts[title]


def _utc(value: Any, event: CalendarEvent, zone: ZoneInfo) -> str:
    """All-day dates are local midnights in the person's zone (end exclusive, as Google gives it)."""
    return format_ts(datetime.combine(value, time(0), tzinfo=zone) if event.all_day else value)
