"""CalendarAdapter: read the events of a person's own primary Google Calendar (FR-CAL-08, FR-CAL-02 read path).

The only module that talks to Google Calendar, and only to `events.list` with the read scope. Google's partial
response mask asks for no description, attendee address or name, link, location or organizer, and every item is
cut down to what PE-13 lets Tilo keep before it leaves this module. One attempt per request: this adapter never
waits or retries (a 401 gets the one forced refresh); the poller backs off. Nothing here logs. Titles are
untrusted text: `clean_title` makes one fit the calendar entry contract, and the sync screens it. API:
tests/API_FR_CAL_08.md.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from .._time import format_ts, parse_ts
from ._google import GoogleAdapter
from ._transport import AdapterError, SyncTokenExpired

if TYPE_CHECKING:
    from ..tokens import TokenBroker
    from ._transport import ApiResponse, Transport

CALENDAR_API = "https://www.googleapis.com/calendar/v3"
EVENTS_URL = CALENDAR_API + "/calendars/primary/events"  # the person's own primary calendar only
CALENDAR_READONLY = "https://www.googleapis.com/auth/calendar.readonly"
EVENT_FIELDS = (
    "items(id,status,summary,start,end,eventType,attendees(self,resource,responseStatus)),nextPageToken,nextSyncToken"
)
NO_TITLE = "(No title)"
REMOVED = "[removed]"
TITLE_MAX = 140  # calendar_entry.title maxLength
TITLE_SCAN = 4096  # code points of a summary looked at; the rest is never read
CONFERENCE_HOSTS = ("meet.google.com", "zoom.us", "teams.microsoft.com")  # meeting.schema.json title rule
MAX_ATTENDEE_COUNT = 500  # calendar_entry.attendee_count maximum
TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_\-=.~+/]{1,4096}")  # a sync or page token
EVENT_ID_SHAPE = re.compile(r"[A-Za-z0-9_-]{1,128}")  # = calendar_entry source_google.ref
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DROPPED = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})  # controls, bidi and format, surrogates, separators (PE-24)
_MAX_INSTANT = 40  # characters of a dateTime looked at


@dataclass(frozen=True)
class CalendarEvent:
    """What leaves the adapter: the PE-13 fields only, already cleaned."""

    event_id: str
    removed: bool  # cancelled, declined by the person, or a working location
    title: str = field(repr=False)  # "" when removed
    start: datetime | date | None = None  # UTC-aware datetime, or a date when all_day; None when removed
    end: datetime | date | None = None  # same kind as start; Google's exclusive end date for all-day
    all_day: bool = False
    attendee_count: int = 0


@dataclass(frozen=True)
class EventPage:
    events: tuple[CalendarEvent, ...]  # Google's order
    skipped: int  # items that are not usable events: counted, never raised, never logged
    next_page_token: str | None = field(default=None, repr=False)
    next_sync_token: str | None = field(default=None, repr=False)  # only on the last page


class _NoArtifacts:  # a read-only adapter saves nothing
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        raise AdapterError("this adapter has no artifacts")


class CalendarAdapter(GoogleAdapter):
    def __init__(
        self,
        *,
        declaration: Mapping[str, Any],
        broker: TokenBroker,
        transport: Transport,
        clock: Callable[[], str],
        emit: Callable[[dict[str, Any]], None],
    ) -> None:
        super().__init__(
            declaration=declaration,
            broker=broker,
            transport=transport,
            artifacts=_NoArtifacts(),
            owner_of=str,
            clock=clock,
            emit=emit,
            sleep=lambda _seconds: None,  # never called: one attempt per request
            max_attempts=1,
        )

    def list_events(
        self,
        user_id: str,
        *,
        page_size: int,
        sync_token: str | None = None,
        time_min: str | None = None,
        time_max: str | None = None,
        page_token: str | None = None,
    ) -> EventPage:
        params: dict[str, Any] = {"maxResults": self._batch(page_size), "singleEvents": "true", "fields": EVENT_FIELDS}
        params.update(_mode(sync_token, time_min, time_max))
        if page_token is not None:
            params["pageToken"] = _token(page_token)
        try:
            response = self._call(user_id, [CALENDAR_READONLY], "GET", EVENTS_URL, params=params)
        except AdapterError as exc:
            if exc.status == 410 and "syncToken" in params:
                raise SyncTokenExpired("Google answered 410: the sync token expired") from None
            raise
        return _page(response, params["maxResults"])


# -- the request ---------------------------------------------------------------------------------------


def _token(value: Any) -> str:
    if not isinstance(value, str) or not TOKEN_SHAPE.fullmatch(value):
        raise ValueError("not a sync or page token")
    return value


def _stamp(value: Any) -> str:
    if not isinstance(value, str) or format_ts(parse_ts(value)) != value:
        raise ValueError("not a common timestamp")
    return value


def _mode(sync_token: Any, time_min: Any, time_max: Any) -> dict[str, str]:
    if sync_token is not None and time_min is None and time_max is None:
        return {"syncToken": _token(sync_token)}
    if sync_token is None and time_min is not None and time_max is not None:
        low, high = _stamp(time_min), _stamp(time_max)
        if parse_ts(low) >= parse_ts(high):
            raise ValueError("time_min is not before time_max")
        return {"timeMin": low, "timeMax": high}
    raise ValueError("list_events takes a sync_token alone, or time_min and time_max")


# -- the answer ----------------------------------------------------------------------------------------


def _page(response: ApiResponse, limit: int) -> EventPage:
    try:
        body = response.json()
    except ValueError:
        raise AdapterError("Google answered without JSON") from None
    if not isinstance(body, dict) or not isinstance(body.get("items", []), list):
        raise AdapterError("Google's answer is not an event list")  # no status: malformed
    items, page_token, sync_token = body.get("items", []), body.get("nextPageToken"), body.get("nextSyncToken")
    for token in (page_token, sync_token):
        if token is not None and not (isinstance(token, str) and TOKEN_SHAPE.fullmatch(token)):
            raise AdapterError("Google's answer has a malformed token")
    if len(items) > limit or (page_token is None) == (sync_token is None):  # too many, or both or neither token
        raise AdapterError("Google's answer is not an event list")
    events = [e for e in map(_event, items) if e is not None]
    return EventPage(tuple(events), len(items) - len(events), page_token, sync_token)


def _event(item: Any) -> CalendarEvent | None:
    """One item, in the order of the API doc's mapping table; None when it is not a usable event."""
    event_id = item.get("id") if isinstance(item, dict) else None
    if not isinstance(event_id, str) or not EVENT_ID_SHAPE.fullmatch(event_id):
        return None
    status = item.get("status")
    if status == "cancelled":
        return CalendarEvent(event_id, True, "")
    if status not in ("confirmed", "tentative"):
        return None
    attendees = item.get("attendees")
    people = [a for a in attendees if isinstance(a, dict)] if isinstance(attendees, list) else []
    if item.get("eventType") == "workingLocation" or any(
        a.get("self") is True and a.get("responseStatus") == "declined" for a in people
    ):
        return CalendarEvent(event_id, True, "")  # a place (PE-13), or the person said no
    span = _span(item.get("start"), item.get("end"))
    if span is None:
        return None
    start, end, all_day = span
    others = sum(1 for a in people if a.get("self") is not True and a.get("resource") is not True)
    title = clean_title(item.get("summary"))
    return CalendarEvent(event_id, False, title, start, end, all_day, min(MAX_ATTENDEE_COUNT, others))


def _span(start: Any, end: Any) -> tuple[datetime | date, datetime | date, bool] | None:
    if not isinstance(start, dict) or not isinstance(end, dict):
        return None
    kinds = [k for k in ("dateTime", "date") if k in start]
    if len(kinds) != 1 or [k for k in ("dateTime", "date") if k in end] != kinds:
        return None
    all_day = kinds[0] == "date"
    first, last = (_day if all_day else _instant)(start[kinds[0]]), (_day if all_day else _instant)(end[kinds[0]])
    if first is None or last is None or (last <= first if all_day else last < first):
        return None  # PE-19: an unparsable or reversed time is skipped, never guessed
    return first, last, all_day


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > _MAX_INSTANT:
        return None
    try:
        moment = datetime.fromisoformat(value)
        return moment.astimezone(UTC) if moment.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) and _DATE.fullmatch(value) else None
    except ValueError:
        return None


def clean_title(value: Any) -> str:
    """Pure; always a valid calendar_entry title. Links, conference hosts and addresses become `[removed]`
    (PE-13); control, bidi and format characters go (PE-24); HTML and instructions stay as literal text."""
    if not isinstance(value, str):
        return NO_TITLE
    text = "".join(c for c in value[:TITLE_SCAN] if unicodedata.category(c) not in _DROPPED)
    title = " ".join(REMOVED if _is_link_or_address(word) else word for word in text.split())
    if len(title) > TITLE_MAX:
        title = title[: TITLE_MAX - 1].rstrip() + "…"
    return title or NO_TITLE


def _is_link_or_address(word: str) -> bool:
    probe = unicodedata.normalize("NFKC", word).casefold()
    return (
        "://" in probe
        or probe.startswith("www.")
        or any(host in probe for host in CONFERENCE_HOSTS)
        or probe.find("@", 1, len(probe) - 1) != -1  # an "@" with a character on each side
    )
