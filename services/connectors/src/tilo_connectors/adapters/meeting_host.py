"""The `meeting_host` adapter: one Google Calendar insert on the meeting bot's own account, with a Meet link and
invitations to the people the Owner approved (FR-MTG-09, ADR-0024; API tests/API_FR_MTG_09.md).

`execute_side_effect` is called only by `Outbox.dispatch_due()` (SEC-03). Every failure after the grant check
raises `SideEffectRefused` unless noted, so the entry ends `failed` with no `data.transfer` and no receipt. The
request asks Google for no link (`fields` mask) and ignores every key of the answer but the event id and the
conference status: the Meet link is stored nowhere (FR-MTG-01). No log line; messages are fixed text plus a code.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .._time import parse_ts
from ..errors import AdapterError, PossiblySent, SideEffectRefused
from ..meeting_host import (
    ACTION_TYPE,
    CALENDAR_EVENTS_OWNED,
    DRAFT_KIND,
    HOST_CALENDAR,
    MAX_RECIPIENTS,
    HostReceipt,
    ReceiptStore,
)
from ..outbox import Grant
from ._google import GoogleAdapter, side_effect_marker
from ._transport import ArtifactSource

EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
EVENT_FIELDS = "id,status,conferenceData(createRequest(status(statusCode)))"  # never hangoutLink
_CONFERENCE_STATUSES = ("pending", "success", "failure")
_DRAFT_TEXT_KEYS = ("meeting_id", "owner", "title", "start", "end", "time_zone")


class MeetingHostAdapter(GoogleAdapter):
    def __init__(
        self,
        *,
        declaration: Mapping[str, Any],
        broker: Any,
        transport: Any,  # a Transport (a live one answers with its own response class)
        artifacts: ArtifactSource,
        owner_of: Callable[[str], str],
        receipts: ReceiptStore,
        clock: Callable[[], str],
        emit: Callable[[dict[str, Any]], None],
        sleep: Callable[[float], None],
    ) -> None:
        super().__init__(
            declaration=declaration,
            broker=broker,
            transport=transport,
            artifacts=artifacts,
            owner_of=owner_of,
            clock=clock,
            emit=emit,
            sleep=sleep,
        )
        self._receipts = receipts

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:
        self._check_grant(entry, grant)  # MissingGrant before anything is read
        recipients = self._checked_entry(entry)
        draft = self._checked_draft(entry, recipients)
        owner = draft["owner"]
        if not parse_ts(self._clock()) < parse_ts(draft["start"]):  # MH-12
            raise SideEffectRefused("MH-12: the meeting has started")
        marker = side_effect_marker(entry)
        scopes = [CALENDAR_EVENTS_OWNED]
        body = {
            "id": marker,
            "summary": draft["title"],
            "start": {"dateTime": draft["start"], "timeZone": draft["time_zone"]},
            "end": {"dateTime": draft["end"], "timeZone": draft["time_zone"]},
            "attendees": [{"email": address} for address in recipients],
            "conferenceData": {
                "createRequest": {"requestId": marker, "conferenceSolutionKey": {"type": "hangoutsMeet"}}
            },
            "guestsCanInviteOthers": False,
            "guestsCanModify": False,
            "guestsCanSeeOtherGuests": False,
        }
        params = {"conferenceDataVersion": 1, "sendUpdates": "all", "fields": EVENT_FIELDS}
        try:
            # NotConnected, ConnectionExpired and InsufficientScope propagate: no attempt is spent (the outbox waits)
            answer = self._json(owner, scopes, "POST", EVENTS_URL, params=params, json=body, patient=False)
        except AdapterError as error:
            if error.status in (400, 404):  # can never succeed as written
                raise SideEffectRefused(f"MH-13: Google refused the invitation ({error.status})") from None
            if error.status != 409:  # a lost answer or a 5xx is ambiguous: retried, and the retry lands on 409
                raise
            answer = self._earlier_event(owner, scopes, marker)
        if answer.get("id") != marker:  # MH-14
            raise PossiblySent("MH-14: Google answered another event")
        status = (((answer.get("conferenceData") or {}).get("createRequest") or {}).get("status") or {}).get(
            "statusCode"
        )
        conference = status if status in _CONFERENCE_STATUSES else "pending"
        receipt = HostReceipt(
            world_id=entry["world_id"],
            outbox_id=entry["id"],
            meeting_id=draft["meeting_id"],
            owner=owner,
            draft={"artifact_id": entry["item"]["artifact_id"], "version": entry["item"]["version"]},
            event_ref=marker,
            conference=conference,
        )
        return {"receipt": self._receipts.put(receipt), "conference": conference}

    def _checked_entry(self, entry: Mapping[str, Any]) -> list[str]:
        """MH-10: the entry is a meeting invitation a person approved."""
        recipients, authz = entry.get("recipients"), entry.get("authz")
        if not (
            isinstance(recipients, list)
            and 1 <= len(recipients) <= MAX_RECIPIENTS
            and all(isinstance(address, str) for address in recipients)
            and isinstance(authz, Mapping)
            and authz.get("by") == "person"
        ):
            raise SideEffectRefused("MH-10: the entry is not a meeting invitation the owner approved")
        if not (
            entry.get("action_type") == ACTION_TYPE
            and entry.get("connector") == self.id
            and entry.get("risk_tier") == "T3"
            and "new_recipients" in (entry.get("modifiers") or [])
            and entry.get("attachments") == []
            and entry.get("destination") == HOST_CALENDAR
            and entry.get("item") is not None
            and entry.get("undo_window_s") == 0
        ):
            raise SideEffectRefused("MH-10: the entry is not a meeting invitation the owner approved")
        return list(recipients)

    def _checked_draft(self, entry: Mapping[str, Any], recipients: list[str]) -> Mapping[str, Any]:
        """MH-11: the hash-checked draft is the owner's, and the entry invites exactly its list."""
        try:
            draft = self._artifact(entry["item"], DRAFT_KIND)
            well_formed = all(isinstance(draft.get(key), str) for key in _DRAFT_TEXT_KEYS)
        except SideEffectRefused:
            raise
        except Exception:  # noqa: BLE001 - a store error text must not travel
            raise SideEffectRefused("MH-11: the draft cannot be read") from None
        if not well_formed:
            raise SideEffectRefused("MH-11: the draft is malformed")
        if not (self._owner_of(entry["world_id"]) == draft["owner"] == entry["authz"].get("ref")):
            raise SideEffectRefused("MH-11: the draft is not the owner's")
        if draft.get("attendees") != recipients:
            raise SideEffectRefused("MH-11: the recipients are not the approved ones")
        return draft

    def _earlier_event(self, owner: str, scopes: list[str], marker: str) -> dict[str, Any]:
        """MH-13: a 409 means an earlier attempt created the event; read it, never insert again."""
        try:
            event = self._json(owner, scopes, "GET", f"{EVENTS_URL}/{marker}", params={"fields": EVENT_FIELDS})
        except AdapterError as error:
            if error.status == 404:
                raise PossiblySent("MH-13: the earlier event cannot be found") from None
            raise
        if event.get("status") == "cancelled":
            raise PossiblySent("MH-13: the earlier event was cancelled")
        return event
