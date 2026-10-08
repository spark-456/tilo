# Join a hosted meeting from Tilo's calendar: what the tests pin (ADR-0024 amendment 4, tickets JOIN-a to JOIN-d)

Spec: ADR-0024 amendment 4 (Accepted, the user's approval of 8 Oct 2026), `contracts/meeting_join.schema.json` 1.0.0,
`contracts/meeting_join.rules.md` MJ-01 to MJ-10, `calendar_entry.schema.json` 1.1.0 (`agenda_item.joinable`), PE-13,
`services/connectors/tests/API_FR_MTG_09.md` (PPL-60c `join_link`, MH-20, MH-21) and `API_MTG09_b.md` (the host run,
the receipt). Open points: `docs/open-questions.md` BQ-JOIN-1 to BQ-JOIN-6. Tests first (test-writer), names carry
`FR_MTG_09` and the ticket (`test_FR_MTG_09_JOIN_b_owner_only`). Nothing here makes a network call, calls a model or reads
`LIVE`; Google is `FakeHostCalendar` (`_meeting_host_lib.py`) with a planted `hangoutLink`.

## JOIN-a: `MeetingHostAdapter.join_link` (services/connectors, CL-REACH; security review)

```python
JOIN_FIELDS = "status,hangoutLink"  # the one place hangoutLink is asked for; EVENT_FIELDS is unchanged
JOIN_LINK = re.compile(r"https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}")  # fullmatch only


def join_link(self, owner: str, event_ref: str) -> str: ...  # or raises MeetingHostRefused (MH-20, MH-21)
```

- `event_ref` fullmatches `[0-9a-f]{32}` (the receipt's marker), else MH-20 before any request.
- One `GET EVENTS_URL/{event_ref}`, `params == {"fields": JOIN_FIELDS}`, through `self._call(owner,
  [CALENDAR_EVENTS_OWNED], ..., patient=False)`: the `(owner, "meeting_host")` token, no waiting retry. `NotConnected`,
  `ConnectionExpired`, `InsufficientScope` and `ProviderUnavailable` propagate unchanged.
- Google 404 or 410, or `status == "cancelled"`: `MeetingHostRefused("MH-20", ...)`. No `hangoutLink`, a non-string, or
  one that does not fullmatch `JOIN_LINK`: `MeetingHostRefused("MH-21", ...)`. Every other key of the answer is ignored.
- Returns the string. No log line, no emit, no store; exception messages are fixed text plus the rule id, never the
  value (a planted `https://meet.google.com/zzz-yyyy-xxx/../x` appears in no message, `caplog` record or `repr`).
- Hostile: an answer with `hangoutLink` `http://meet.google.com/...`, `https://meet.google.com.example.org/...`,
  `https://meet.google.com/abc-defg-hij?authuser=1`, a trailing newline, `javascript:...`: MH-21 each. The fake
  records exactly one GET per call and never a POST, PUT, PATCH or DELETE. `adapters/calendar.py` is untouched (its
  privacy tests still forbid `hangoutLink`).
- PPL-60c's other caller (the bot's start request) is still later work; this ticket adds the method and its tests.

## JOIN-b: `GET /v1/meetings/{meeting_id}/join` (services/api, CL-PEOPLE or CL-INT; security review)

Behind the SEC-15 gate and App Check like every `/v1/` route; `Cache-Control: no-store` (the middleware); principal
`deps.Principal.user_id`; org `deps.ORG_ID`; clock `deps.get_clock`. Seams: `get_people_stores`, `get_store`,
`get_artifact_store`, `get_connector_registry`, `get_token_broker`, `get_meeting_host_transport` (the MTG09-b seams; an
unwired one is 503 `not_configured`). The route builds a `MeetingHostAdapter` per request from those seams, as
`HostRun` does, and calls only `join_link`.

| Answer | When |
| --- | --- |
| 200 `{"join_url", "expires_at"}` (validates against `meeting_join.schema.json`) | MJ-01 to MJ-04 pass |
| 404 (one body, byte-equal for every case) | malformed id, unknown or other-org meeting, not the owner, deleted meeting (MJ-01, PE-05) |
| 409 `not_joinable` | status not `scheduled`/`joining`/`live`, source not `bot`, no host receipt in the meeting's world, a receipt of another meeting, MH-20 (MJ-02, MJ-03) |
| 409 `no_join_link` | MH-21, or the body fails the contract (MJ-04) |
| 409 `host_not_connected` | `NotConnected`, `ConnectionExpired`, `InsufficientScope` on `(owner, "meeting_host")` |
| 429 `rate_limited` + `Retry-After` | the 11th join of a principal within 60 s, counted before Google is asked (MJ-08) |
| 503 `try_again` / `not_configured` | `ProviderUnavailable` (Google 429, 5xx, timeout, lost answer) / an unwired seam |

- The receipt (MJ-02): in the meeting's world (`meeting["world_id"]`, owner checked against `Store.worlds`), the
  `artifact.created` whose `cause` is a `data.transfer` with `connector == "meeting_host"` and `direction == "out"`; its
  bytes through `ArtifactStore.read(Scope(ORG_ID, world_id, owner), ref)` (hash-checked) parse as
  `{"kind": "meeting_event_receipt", "meeting_id": <this meeting>, "event_ref": ...}`. No request field names a world,
  ref or event id. Several receipts: the latest by event `seq` (BQ-JOIN-4).
- `expires_at` = `get_clock()` + 60 s, in the common timestamp form (MJ-06).
- MJ-05 test: after a 200, the planted link occurs in no emitted part, `Store.events`, people store, artifact store,
  outbox row, card, archive record, `caplog` record (every logger, DEBUG) or exception text, only in the response body.
- MJ-09 test: the world's event count and `seq` are unchanged by any join answer; no run, outbox entry or model call.
- `agenda_item.joinable` (JOIN-d, with the FR-CAL-01 agenda route): true exactly when this route would pass MJ-01 and
  MJ-02 for the reader (no Google call at agenda time); a `google`-sourced copy of the hosted event is never joinable.

## JOIN-c: the web (apps/web, Agenda and S-26; design-critic and qa-breaker)

- `Api.joinMeeting(meetingId: string): R<MeetingJoin>` (the `@tilo/contracts` type) on the Park Api; the fixture Api
  answers `not-built` (a preview never opens a real Meet URL). The Agenda event and S-26 meeting detail show Join only
  where the row's `joinable` is true (fixture rows may set it; the Park `AgendaEvent` gains `meetingId` and `joinable`).
- On the click (never on load, hover or selection alone): call `joinMeeting`; check MJ-07, the contract's pattern
  `^https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}$` and `new URL(u)`: origin `https://meet.google.com`, empty
  `username`, `password`, `search` and `hash`; open with `window.open(u, "_blank", "noopener,noreferrer")` inside the click's activation. If the
  open is blocked or the answer took longer than the activation, the event detail shows "Join the call" as
  `<a href={u} target="_blank" rel="noopener noreferrer">`, held in component state only until `expires_at` or unmount.
- Refusals show fixed text, never a server string: `not_joinable` "This meeting has no Meet call from Tilo.",
  `no_join_link` "Google has not added a Meet link yet.", `host_not_connected` "Reconnect the meeting host in
  Connections.", 429 and 503 "Try again in a moment."
- Tests: the link never reaches `localStorage`, `sessionStorage`, `history.state`, `location`, `console.*` or the error
  reporter (spies); a hostile `join_url` (each `contracts/fixtures/meeting_join/invalid/*` value) is never opened and no
  anchor renders; the anchor carries exactly `rel="noopener noreferrer"`; after `expires_at` (fake timers) the anchor is
  gone and a click asks again. No new console errors, no layout shift.

## Not in these tickets

Joining for invitees other than the owner (BQ-JOIN-2), audit events for joins (BQ-JOIN-5), a "copy link" control
(none: copying would put the link on the clipboard), and the bot's own start request (PPL-60c).
