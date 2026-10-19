"""CalendarWriteAdapter: the one place a person's own primary Google Calendar is written (ADR-0035 LC-09, FR-CAL-04).

Kept apart from `calendar.py`, whose module (with the sync path) holds no write verb (test_FR_MTG_09_hostile). Two
outbox actions, both an `events.insert` on the primary calendar with the id derived from the outbox marker, so a
re-attempt after a lost answer reads the first event instead of making a second (OB-03):
`create_event` has no guests and refuses any before a request is made (LC-09); `create_event_with_guests` is the T3
action that invites exactly the entry's recipients and lets Google email them. The scope comes from the declaration.
`execute_side_effect` runs only under an outbox grant (SEC-03). Nothing here logs; messages are fixed text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._time import parse_ts
from ..errors import AdapterError, PossiblySent, SideEffectRefused
from ..outbox import Grant
from ._google import GoogleAdapter, side_effect_marker
from .calendar import EVENTS_URL

_KIND = "calendar_event"
_FIELDS = "id,status"  # never a link, a title or an address
_LOOKUP_FIELDS = "id,status,organizer(self)"
_TEXT_KEYS = ("title", "start", "end", "time_zone")
_MAX_GUESTS = 50
_MAX_TEXT = 1024


class CalendarWriteAdapter(GoogleAdapter):
    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:  # the only one (SEC-03)
        self._check_grant(entry, grant)
        action = entry.get("action_type")
        if action not in ("create_event", "create_event_with_guests"):
            raise SideEffectRefused("google_calendar has no side effect for this action")
        return self._done(self._final_on_rejection(lambda: self._insert(entry, guests=action != "create_event")))

    def _insert(self, entry: Mapping[str, Any], *, guests: bool) -> dict[str, Any]:
        if entry.get("destination") not in (None, "primary"):
            raise SideEffectRefused("only the own primary calendar is written")
        recipients = entry.get("recipients")
        document = self._document(entry)
        listed = document.get("attendees", [])
        if not guests:  # LC-09: any guest, in the entry or in the document, before the first request
            if recipients or listed or "guests" in document or entry.get("attachments"):
                raise SideEffectRefused("create_event has no guests")
            attendees: list[str] = []
        else:
            if not (isinstance(recipients, list) and 1 <= len(recipients) <= _MAX_GUESTS):
                raise SideEffectRefused("the guests are not the approved recipients")
            if not all(isinstance(a, str) for a in recipients) or listed not in ([], recipients):
                raise SideEffectRefused("the guests are not the approved recipients")
            attendees = list(recipients)
        marker, user = side_effect_marker(entry), self._owner_of(str(entry["world_id"]))
        scopes = self._scopes("send" if guests else "write")
        if (earlier := self._earlier(user, scopes, marker)) is not None:
            return earlier  # OB-03: a lost answer, a crash or another instance already did it
        body: dict[str, Any] = {
            "id": marker,
            "summary": document["title"],
            "start": {"dateTime": document["start"], "timeZone": document["time_zone"]},
            "end": {"dateTime": document["end"], "timeZone": document["time_zone"]},
            "guestsCanInviteOthers": False,
            "guestsCanModify": False,
        }
        if attendees:
            body["attendees"] = [{"email": address} for address in attendees]
            body["guestsCanSeeOtherGuests"] = False
        params = {"sendUpdates": "all" if attendees else "none", "fields": _FIELDS}
        try:
            made = self._json(user, scopes, "POST", EVENTS_URL, params=params, json=body, patient=False)
        except AdapterError as error:
            if error.status != 409:  # 400 and 404 are final (the caller), the rest is retried
                raise
            if (found := self._earlier(user, scopes, marker)) is None:
                raise PossiblySent("Google reported an earlier event that cannot be read") from None
            return found
        if made.get("id") != marker:
            raise PossiblySent("Google answered another event")
        return {"id": marker}

    def _document(self, entry: Mapping[str, Any]) -> Mapping[str, Any]:
        item = self._artifact(entry.get("item"), _KIND)
        text = [item.get(key) for key in _TEXT_KEYS]
        if not all(isinstance(t, str) and 0 < len(t) <= _MAX_TEXT for t in text):
            raise SideEffectRefused("the event cannot be made as written")
        try:
            if not parse_ts(item["start"]) < parse_ts(item["end"]):
                raise ValueError("ends before it starts")
        except ValueError:
            raise SideEffectRefused("the event cannot be made as written") from None
        return item

    def _earlier(self, user: str, scopes: list[str], marker: str) -> dict[str, Any] | None:
        """The event an earlier attempt made under this marker, else None. Cancelled counts as made: it was sent."""
        try:
            found = self._json(
                user, scopes, "GET", f"{EVENTS_URL}/{marker}", params={"fields": _LOOKUP_FIELDS}, patient=False
            )
        except AdapterError as error:
            if error.status == 404:
                return None
            raise
        organizer = found.get("organizer")
        mine = isinstance(organizer, Mapping) and organizer.get("self") is True  # not an event we were invited to
        if found.get("status") == "cancelled" or found.get("id") != marker or not mine:
            raise PossiblySent("an earlier event under this marker was cancelled, not ours, or cannot be read")
        return {"id": marker}
