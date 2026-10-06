# Bot-hosted meeting and invites — public API these tests pin (FR-MTG-09 as amended 6 Oct 2026)

Source: the user's decision of 6 Oct 2026, relayed by the supervisor: "Have the bot start the meeting instead
and then send invites to scheduled people." FR-MTG-09 (`docs/prd-addendum-people-agents.md` 3.1) moves from
the guest-join experiment to a **bot-hosted meeting**: the meeting bot's own Google account creates a Google
Calendar event with a Google Meet link, as organizer, and Google invites the scheduled attendees. Decisions:
ADR-0024 (amends ADR-0017). Defaults: `docs/open-questions.md` BQ-MTG09-1 to BQ-MTG09-12. Supplement note:
`docs/prd-supplement-note-mtg09-2026-10-06.md`.

Contracts used as they are (**no contract change**): `connector.schema.json` (a new entry validates),
`outbox.schema.json` + OB-01..OB-05, `card.schema.json` + CR-09..CR-12, `artifact.schema.json` + AR-01..AR-07,
`meeting.schema.json` (no link field: "the bot receives it in its start request and nothing stores it"),
`person.schema.json`, `people.rules.md` PE-05, PE-09, PE-12, PE-13, PE-14, PE-18, PE-20, PE-21, events
`approval.requested`, `approval.resolved`, `data.transfer`, `artifact.created`, `connection.*`. `action_type`
and `connector_id` are pattern-checked slugs, so `create_meeting_event` and `meeting_host` need no schema edit.

Builds on the outbox (`API.md`), the adapter conventions (`API_FR_CON_04_05.md`: `execute_side_effect`,
`SideEffectRefused`, `side_effect_marker`), the calendar read path (`API_FR_CAL_08.md`, which stays read-only)
and the build-handoff model of an external side effect (`API_FR_CON_16_17_20.md`).

Suggested test files: `test_FR_MTG_09_config.py`, `test_FR_MTG_09_draft.py`, `test_FR_MTG_09_host_flow.py`,
`test_FR_MTG_09_hostile.py`, `test_FR_MTG_09_grant_groups.py`; doubles in `_meeting_host_lib.py`. Nothing here
makes a network call, calls a model or reads `LIVE`.

## The decision in short

- **Organizer: the meeting bot's own Google account** (the account ADR-0017 already defines: created by the
  user, used by nothing else), connected to Tilo as the connector `meeting_host`. Only the organizer is the Meet
  host, so this is the one choice where "the bot starts the meeting" holds; on the Owner's calendar the Owner is
  host and the bot is still a guest who must be admitted. It is also least privilege for people: every
  person's own Calendar grant stays `calendar.readonly` (FR-CAL-08 unchanged, no re-consent); the only write
  scope sits on an account that holds no personal data.
- **Scope:** `https://www.googleapis.com/auth/calendar.events.owned` on the host account only. No Meet API
  scope: the link comes from `events.insert` with `conferenceData.createRequest` and `conferenceDataVersion=1`
  (Google Calendar API docs, checked 6 Oct 2026).
- **Tier: always T3.** `create_meeting_event` is listed T3 and every hosted event invites at least the Owner,
  so `attendee_count > 0` and `new_recipients` applies (PE-14). There is no T1 path for a bot-hosted meeting;
  the T1 own-calendar path is FR-CAL-04's `create_event` (PPL-70), untouched.
- **The Meet link is never stored** (FR-MTG-01, `meeting.schema.json`). The insert asks Google for no link
  (`fields` mask); Tilo keeps only Google's event id in a receipt artifact. The bot gets the link in its start
  request: today the Owner copies it from their own invitation; later `join_link` (PPL-60c) hands it over in
  memory.

## Shipped config (added by build ticket MTG09-a, not by this design commit)

Not added now: a new `config/connectors.yaml` entry changes the Director's plan-stage replay key (3
`evals/tests/test_PL_LIVE_E2E_*` tests fail until `evals/tests/regen_live_e2e_fixture.py` regenerates
`evals/bank/live/B-007`, which sets `LIVE=1` in its process: the orchestrator or the user runs it), and it
would offer the Director an action with no adapter. `test_FR_CAL_08_config.py` dumps only the
`google_calendar` entry, so a separate `meeting_host` entry leaves it green.

```yaml
# config/connectors.yaml, appended after google_calendar
- id: meeting_host
  name: Tilo meeting host
  icon: calendar
  auth: oauth2
  scopes:
    send: ["https://www.googleapis.com/auth/calendar.events.owned"]
  capabilities: [send]
  actions:
    - {id: create_meeting_event, capability: send, description: "On the meeting bot's own Google account (sign in as the bot, not as yourself): create a meeting with a Meet link and invite the people you approve.", risk_tier: T3, gate_type: approval, irreversible: true}
  limits: {per_minute: 30, batch_size: 50}
  data_class: {returns: [business], redact: []}
```

- `config/autonomy.yaml`: `create_meeting_event: T3`, listed (not left to the unlisted-is-T3 default) with a
  comment, like `build_handoff`. `tilo_policy.load_risk_table().assess("create_meeting_event",
  SideEffectFacts(recipients=("o@example.com",)))` is `Assessment("T3", ("new_recipients",))`.
- `config/personal.yaml` gains `meeting_host: {max_duration_min: 60}` (1..1440; Google ends a free account's
  group call at 60 minutes and the bot counts as a participant, BQ-MTG09-9). Loader below; the
  `load_calendar_sync_config` loader already ignores other top-level keys.

## Errors (`tilo_connectors.errors`, added)

```python
class MeetingHostConfigError(ValueError): ...  # names the key, never a value; message at most 500 characters


class MeetingHostRefused(ValueError):
    rule: str  # "MH-01" .. "MH-07" (draft and gate) or "MH-20", "MH-21" (join_link)
    # The message names the rule and ids only: never a title, an address, a time, a URL or a token.
```

The adapter raises the existing `SideEffectRefused` / `PossiblySent` (rules MH-10 to MH-14 in the message).

## `tilo_connectors.meeting_host`

```python
CONNECTOR_ID = "meeting_host"
ACTION_TYPE = "create_meeting_event"
CALENDAR_EVENTS_OWNED = "https://www.googleapis.com/auth/calendar.events.owned"
HOST_CALENDAR = "primary"  # the outbox destination: the host account's own primary calendar
DRAFT_KIND = "meeting_event"
EXACT_MAX = 500  # card.schema.json gate_action.exact


@dataclass(frozen=True)
class MeetingHostConfig:
    max_duration_min: int  # 1..1440


def load_meeting_host_config(
    path: str | os.PathLike[str] = DEFAULT_PERSONAL_CONFIG, *, registry: ConnectorRegistry
) -> MeetingHostConfig: ...
```

The loader refuses (`MeetingHostConfigError`) a missing `meeting_host` block, a key other than
`max_duration_min`, a bool or non-int or out-of-range value, a registry without `meeting_host`, and a
`meeting_host` declaration whose scopes are not exactly `{send: [CALENDAR_EVENTS_OWNED]}` or whose
`create_meeting_event` is not `send`, T3, `approval`, irreversible (MH-07).

```python
@dataclass(frozen=True)
class MeetingEventDraft:
    meeting_id: str
    org_id: str
    owner: str  # the meeting owner's user id
    title: str = field(repr=False)
    start: str  # common timestamp (UTC), from meeting.scheduled.start
    end: str  # common timestamp (UTC), from meeting.scheduled.end
    time_zone: str  # the owner's person.time_zone
    recipients: tuple[str, ...] = field(repr=False)  # owner's address first, then invitees in attendee order
    invited: tuple[str, ...]  # user ids, same order as recipients
    not_invited: int  # attendees with no Tilo account (attendees[].user is null)
    content: bytes = field(repr=False)  # the draft artifact, canonical JSON (below)
    content_sha256: str  # sha256(content), lower-case hex
    exact: str = field(repr=False)  # gate.action.exact


def draft_meeting_event(
    *,
    meeting: Mapping[str, Any],  # the stored meeting record; tilo-api reads it, never a request body
    persons: Mapping[str, Mapping[str, Any]],  # person records by id: the owner and every attendee user
    actor: str,  # the signed-in principal (tilo-api session, never input)
    now: str,  # server clock, common timestamp
    config: MeetingHostConfig,
) -> MeetingEventDraft: ...  # or raises MeetingHostRefused
```

No side effect, no network, no model. Checks in this order; the first failure raises:

| Rule | Check |
| --- | --- |
| MH-01 | `meeting` passes `meeting.schema.json`; `actor == meeting["owner"]`; `status == "scheduled"`; `source == "bot"`; `attestation.by == owner` (PE-18) |
| MH-02 | `scheduled` and `scheduled.end` are not null; `now < start < end`; `end - start <= max_duration_min` |
| MH-03 | every person record passes `person.schema.json` and has `org_id == meeting["org_id"]`; the owner and every non-null `attendees[].user` have a record (a missing one refuses: fail closed). Recipients are the owner's `email`, then the `email` of each attendee user other than the owner, first occurrence only. Attendees with `user` null count in `not_invited` and are never invited. Two users with the same address (NFKC casefold) refuse. At most 50 recipients (outbox and card `maxItems`) |
| MH-04 | the owner's `time_zone` is known to `zoneinfo` (the `tzdata` package is already a dependency) |
| MH-05 | the title is `meeting["title"]` unchanged (the meeting schema already refuses links and control characters) |
| MH-06 | `len(exact) <= EXACT_MAX`; never cut |

Nothing but `meeting` and `persons` reaches the draft: there is no parameter for an address, a free text, a
transcript, minutes, a mail or a model output, so nothing a model, a transcript or an email names can be invited
(PE-09 pattern).

`content` = `json.dumps({"v": "1.0", "kind": "meeting_event", "meeting_id", "owner", "title", "start", "end",
"time_zone", "attendees": list(recipients), "conference": "hangoutsMeet", "send_updates": "all",
"guests_can_invite_others": False, "guests_can_modify": False, "guests_can_see_other_guests": False},
sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")`.

`exact` (start and end shown in the owner's zone, `%a %d %b %Y, %H:%M` to `%H:%M`, then the zone name; `k` is
`not_invited`, `n` is `len(recipients)`):
`f'Creates "{title}" on the Tilo meeting host\'s Google Calendar, {when} ({time_zone}), with a new Google Meet
link. Google emails an invitation from the meeting host account to the {n} people listed, you included.
{skipped}Guests cannot add people or see each other\'s addresses. An invitation cannot be unsent.'` with
`skipped = f"{k} attendee{'s' if k != 1 else ''} without a Tilo account {'are' if k != 1 else 'is'} not
invited. "` when `k > 0`, else `""`.

```python
def host_gate(draft: MeetingEventDraft, stored: Mapping[str, Any], declaration: Mapping[str, Any]) -> dict: ...
```

`stored` is the `artifact.schema.json` record the artifact store returned for `content`. Refuses (MH-07) unless
`declaration` is the `meeting_host` entry with `create_meeting_event` `send`, T3, `approval`, irreversible;
`stored["media_type"] == "application/json"`, `stored["content_sha256"] == draft.content_sha256` (the store's
redactor changed nothing) and `stored["origin"]["kind"] == "unit"`. Returns what the card builder,
`approval.requested` and the outbox entry copy (CR-10 to CR-12, OB-05):

```python
{
    "action_type": "create_meeting_event",
    "connector": "meeting_host",
    "risk_tier": "T3",
    "irreversible": True,
    "modifiers": ["new_recipients"] + (["safety_flag"] if stored["screening"] != "clean" else []),
    "recipients": list(draft.recipients),
    "attachments": [],
    "item": {"artifact_id": ..., "version": ...},  # stored["artifact"] without a label
    "destination": "primary",
    "exact": draft.exact,
    "undo_window_s": 0,
}
```

`modifiers` equals `assess(ACTION_TYPE, SideEffectFacts(recipients=draft.recipients, known_recipients=(),
safety_flags=stored["screening"] != "clean")).modifiers`. A flagged draft still gates (T3 with `safety_flag`,
PE-21); it is not refused.

```python
@dataclass(frozen=True)
class HostReceipt:
    world_id: str
    outbox_id: str
    meeting_id: str
    owner: str
    draft: Mapping[str, Any]  # artifact_ref of the draft, no label
    event_ref: str  # Google's event id: side_effect_marker(entry), [0-9a-f]{32}
    conference: str  # "pending" | "success" | "failure", Google's createRequest status


class ReceiptStore(Protocol):  # production: the artifact store bound to the world's Scope, origin unit
    def put(self, receipt: HostReceipt) -> dict: ...  # artifact_ref; the same (world_id, outbox_id) and the
    # same receipt return the same ref; a different receipt under that key raises SideEffectRefused
    def get(self, world_id: str, meeting_id: str) -> HostReceipt | None: ...


class InMemoryReceiptStore: ...  # dev and tests; `.receipts` lists what it stored
```

The receipt's stored bytes: canonical JSON `{"v": "1.0", "kind": "meeting_event_receipt", "connector",
"calendar": "primary", "event_ref", "meeting_id", "draft", "outbox_id", "conference"}`. No link, no address,
no title, no time.

## `tilo_connectors.adapters.meeting_host`

```python
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
EVENT_FIELDS = "id,status,conferenceData(createRequest(status(statusCode)))"  # never hangoutLink


class MeetingHostAdapter(GoogleAdapter):
    def __init__(
        self, *, declaration, broker, transport, artifacts, owner_of, receipts, clock, emit, sleep
    ) -> None: ...

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict: ...
```

`execute_side_effect` is called only by `Outbox.dispatch_due` (SEC-03; `SIDE_EFFECT_METHOD_NAMES` is
unchanged). In order; every failure after step 1 raises `SideEffectRefused` unless noted, so the entry ends
`failed` with no `data.transfer` and no receipt:

1. `self._check_grant(entry, grant)`: no valid Grant raises `MissingGrant` before anything is read.
2. MH-10 the entry: `action_type == ACTION_TYPE`, `connector == self.id`, `risk_tier == "T3"`,
   `"new_recipients" in modifiers`, `attachments == []`, `destination == "primary"`, `item` not None,
   `authz.by == "person"`, `undo_window_s == 0`, 1 to 50 `recipients`.
3. MH-11 the draft: `self._artifact(entry["item"], "meeting_event")` (the store's hash-checked read, AR-01);
   `owner = self._owner_of(entry["world_id"])` and `owner == draft["owner"] == entry["authz"]["ref"]`;
   `list(entry["recipients"]) == draft["attendees"]` exactly (no one added, dropped or reordered).
4. MH-12 the time: `clock() < draft["start"]`: an invitation never goes out for a meeting that has started.
5. The request, through `self._call(owner, [CALENDAR_EVENTS_OWNED], ...)` with `patient=False` (a side effect
   never waits). `NotConnected`, `ConnectionExpired` and `InsufficientScope` propagate: the outbox waits for a
   person and spends no attempt.

```text
POST EVENTS_URL
params: {"conferenceDataVersion": 1, "sendUpdates": "all", "fields": EVENT_FIELDS}
json: {
  "id": side_effect_marker(entry),
  "summary": draft["title"],
  "start": {"dateTime": draft["start"], "timeZone": draft["time_zone"]},
  "end": {"dateTime": draft["end"], "timeZone": draft["time_zone"]},
  "attendees": [{"email": a} for a in entry["recipients"]],
  "conferenceData": {"createRequest": {"requestId": side_effect_marker(entry),
                                        "conferenceSolutionKey": {"type": "hangoutsMeet"}}},
  "guestsCanInviteOthers": false, "guestsCanModify": false, "guestsCanSeeOtherGuests": false
}
```

   No description, location, attachment, reminder or colour. The marker is 32 lower-case hex characters, which
   Google accepts as an event id (base32hex, 5 to 1024 characters), so a retry of the same entry asks for the
   same id.
6. MH-13 a 409 (the id exists: an earlier attempt created it): `GET EVENTS_URL/{marker}` with `fields:
   EVENT_FIELDS` (a read, patient). A present, not `cancelled` event is the result; a missing or `cancelled`
   one raises `PossiblySent` (final, alert: invitations may have gone out). No second insert, ever. A 400 or
   404 on the insert raises `SideEffectRefused` (`_final_on_rejection`); a lost answer raises
   `ProviderUnavailable` (ambiguous, retried, and the retry lands on this 409 path).
7. MH-14 the answer: `id == marker`, else `PossiblySent`. `conference` is the answer's `statusCode` when it is
   `pending`, `success` or `failure`, else `pending`. Every other key of the answer is ignored and never
   copied, even if Google sends a link or attendee list.
8. `receipts.put(HostReceipt(...))`. An exception from `put` other than `SideEffectRefused` propagates (the
   outbox retries; step 6 then returns the same event and `put` the same ref).
9. Returns `{"receipt": <artifact_ref>, "conference": conference}`. It emits nothing itself: the outbox emits
   the one `data.transfer` out (`artifact` = the draft `item`, `authz` = the entry's). No log line anywhere in
   the module; exception messages are fixed text plus a status code.

A `conference` of `failure` is still `sent` (Google created the event and sent the invitations); the wiring
raises a `needs_you` card "Google did not add a Meet link" (ids only).

## Token broker: a second Google account (`tokens.py`, `consent.py`)

The broker keys grants by `(user_id, connector)` and treats all of one user's connectors as one Google grant
(CON-D10: never revoke while a sibling is connected). The `meeting_host` grant belongs to another Google
account, so:

```python
GRANT_GROUPS: Mapping[str, str] = {"meeting_host": "meeting_host"}  # every other connector: "person"


def grant_group(connector: str) -> str: ...
```

- `has_live_grant(user_id, *, excluding=None)` counts only connectors in the group of `excluding` (or
  `"person"`); `discard_tokens` and the disconnect sibling check use the connector's own group. `delete_user`
  still disconnects every connector, both groups.
- MH-C1 (consent callback, `meeting_host` only): Google's `scope` answer (with `include_granted_scopes=true`)
  must hold nothing but `CALENDAR_EVENTS_OWNED`. Any other scope means the account already granted this client
  Gmail, Drive or Calendar read: a person's own account, not the bot's. Refuse with `ConsentRefused("this is
  not the meeting bot account: sign in with the bot's account")` and discard the tokens **without** revoking
  (a revoke would end that account's other grant, CON-D10). This is a heuristic, not proof (BQ-MTG09-11).

## Ordered flow (who calls what)

1. The Owner, signed in on web or mobile web, asks to host a scheduled bot meeting on S-26:
   `POST /v1/meetings/{id}/host` (MTG09-b). Anyone but the owner gets the meeting's 404 (PE-05). No email, chat
   message, transcript or model output starts this.
2. Not connected: the consent card for `meeting_host`, capability `send` (`ConsentService.build_consent_card`,
   CR-13). The person signs in to Google as the bot account in their own browser; Tilo never sees a password.
3. tilo-api reads the stored meeting and the person records of its owner and attendee users (server side,
   PE-20) -> `draft_meeting_event(...)` -> the draft. No side effect.
4. The host unit of a fixed one-unit plan in the meeting's world (no Director call, the D-6 pattern; the world's
   owner is the meeting owner, PE-12) stores `draft.content` as `application/json`, origin `unit`, key
   `f"{run_id}:{unit_id}:{attempt}:0"` (AR-05) -> `host_gate(draft, stored, declaration)`.
5. Policy: `tilo_policy.decide` with the resolver answer `{recipients: draft.recipients, destination:
   "primary", known_recipients: []}` gives T3 with `new_recipients` -> a gate. `approval.requested` (`item` the
   draft ref, `risk_tier` T3, `irreversible` true, `approver` and `team_lead` null) and the gate card:
   `gate.action = {type, connector, exact: draft.exact, item, destination: "primary"}`, `gate.recipients =
   draft.recipients`, `answer_channels: [web, mobile_web]`. The web shows `item` as plain text.
6. The Owner answers in a signed-in session: `approval.resolved`.
7. Only on `approve`: the outbox entry from `host_gate(...)` with the approval's `authz`, `state: queued` ->
   `Outbox.enqueue(entry, evidence)` (`check_entry`, OB-01/OB-05).
8. `Outbox.dispatch_due()` -> `MeetingHostAdapter.execute_side_effect` -> Google creates the event with a Meet
   link and invites the recipients -> receipt stored -> `data.transfer` out (no recipients, no link).
9. The harness (MTG09-b): `artifact.created` for the receipt, its manifest `inputs: [draft ref]`, and the
   draft's `sent` revision with cause the `data.transfer` (AR-06, MF-04), so the receipt traces back to the
   approval (FR-CON-10, FR-MEM-12).
10. The meeting appears on the Owner's S-29 through their own read-only sync (they are an invitee; PE-13 keeps
    title, times and attendee count only).
11. At meeting time the bot is started with the link (today: the Owner pastes it from their own invitation into
    the meet-bot start command; PPL-60c: `join_link`). Signed in as the host account (ADR-0017 session), it
    enters as host, posts the disclosure first (FR-MTG-01) and admits nobody by itself (ADR-0024).

## Acceptance tests: the exact assertions

**FR-MTG-09 (a) nothing before approval.** With `Outbox(store, {"meeting_host": adapter}, emit, clock)` and a
`gate_case(connector="meeting_host", action_type="create_meeting_event", recipients=draft.recipients,
destination="primary", item=ref, risk_tier="T3")` (entry `modifiers` `["new_recipients"]`, `authorised_by`
channel `web`): after steps 1 to 5, `outbox.get(outbox_id) is None`, the fake calendar holds no event and has
sent no invitation, and no part was emitted. `enqueue` with `authorised_by` option `hold` or `edit`, or with
`authorised_by` None, raises `OutboxRefused` and those facts still hold. With `approve`, one `dispatch_due()`
makes exactly one insert, one event and one invitation per recipient, stores one receipt and emits one
`data.transfer` whose `authz` equals the approval's and whose `data.artifact` equals `gate.action.item`.
`adapter.execute_side_effect(entry, None)` raises `MissingGrant` and the fake saw no request.

**FR-MTG-09 (b) the invitation is exactly what the card showed.** The one insert has `params ==
{"conferenceDataVersion": 1, "sendUpdates": "all", "fields": EVENT_FIELDS}`; its body equals step 5 built
from the pinned draft; `[a["email"] for a in body["attendees"]] == card["gate"]["recipients"] ==
entry["recipients"] == draft["attendees"]`; `body["conferenceData"]["createRequest"]["conferenceSolutionKey"]
== {"type": "hangoutsMeet"}`; `summary`, `start`, `end` equal the draft; `entry["item"] ==
card["gate"]["action"]["item"] == reserved_by["data"]["item"] == transfer["data"]["artifact"] ==
receipt.draft`. The request went to `/calendars/primary/events` with the token of `(owner, "meeting_host")`
(broker spy: only `(owner, "meeting_host", (CALENDAR_EVENTS_OWNED,), False)`).

**FR-MTG-09 (c) the link is stored nowhere.** The fake answers every insert and GET with a full event
(planted `hangoutLink`, `htmlLink`, `conferenceData.entryPoints[].uri` and attendee list) whatever `fields`
says. After the whole flow, the planted link and the planted `htmlLink` occur in no emitted part, log record
(every logger, DEBUG, `caplog`), exception message, receipt bytes, outbox row, card or artifact the doubles
stored. Attendee addresses occur only in the outbox entry's `recipients`, the card's `gate.recipients` and the
draft artifact.

**FR-MTG-09 (d) bounds.** `draft_meeting_event` raises `MeetingHostRefused` with the named rule for: an actor
who is not the owner (MH-01), `status` `live` (MH-01), `source` `upload` (MH-01), `end` null (MH-02), a start
not after `now` (MH-02), 61 minutes with `max_duration_min: 60` (MH-02, 60 passes), an attendee user with no
person record or of another org (MH-03), two users with one address (MH-03), 51 recipients (MH-03, 50 passes),
an unknown time zone (MH-04), an `exact` over 500 characters (MH-06, built with a 120-character title and a
long zone name; never cut). The limit comes from the loaded config (a test file changes it).

**FR-MTG-09 (e) the report (the user's live run, `docs/meeting-bot-hosting-report.md`).** Date, accounts by
role only (host account, two test attendees, never an address), browser; the invitation came from the host
account and showed a Meet link; the bot entered as host with no admission prompt; the disclosure was the
first chat line; whether an invited attendee had to knock; `Tilo leave` worked; afterwards the container
holds no browser profile and no volume of one, and no cookie file is in the image or the repository.

## Hostile cases (reviewers will probe these)

| Case | Exact assertion |
| --- | --- |
| Attendee list changed after approval | The Owner edits `meeting.attendees` after `approval.resolved`: the insert carries the approved list (the pinned draft version). A store-side edit of the entry's `recipients` after `enqueue` (the double's raw row) makes step 3 refuse: entry `failed`, no request, no `data.transfer`. Draft bytes replaced under the same ref: the hash-checked read raises, entry `failed` |
| Attendee added by a model | `draft_meeting_event` has no parameter that can carry an address; an AST check finds no import of `tilo_providers`, `tilo_harness` or `tilo_planning` in `meeting_host.py` or `adapters/meeting_host.py`. A minutes action item, transcript line and mail body planted with `eve@example.org` change nothing: the address is in no recipient list, card, request or part |
| Duplicate invite on retry | (1) `enqueue` twice with one `(world_id, idempotency_key)`: one entry (OB-03). (2) The fake creates the event and then raises `TransportError`: `ProviderUnavailable`, then the next dispatch gets 409 and GETs: one event, one invitation per recipient, one receipt, one `data.transfer`. (3) Two `Outbox` instances dispatch at once: one insert (lease) |
| Someone outside the scheduled attendees | A `persons` map with an extra person of the org not on the meeting: not invited. An entry whose recipients add or swap an address (the draft unchanged): MH-11 refuses before any request |
| Email-spoofed instruction | An inbound `channel.message_in` asking to host or invite starts no host run (only the signed-in route does); an `approval.resolved` with channel `email` (or `whatsapp`) opens nothing (OB-01): no entry, no request |
| Policy tries to open the gate | An owner's policy for `create_meeting_event` at L2 or L3 whose scope covers the recipients: `decide` still gates (T3 max level L1). A hand-built entry with `authz.by: policy` (or `team_lead` with no allowance): `enqueue` raises `OutboxRefused` (OB-04, OB-01). Another person's approval: `open_gate` does not run |
| Owner as the only attendee | Attendees `[owner]` or `[owner, unresolved]`: `recipients == (owner_email,)`, tier T3, `modifiers == ["new_recipients"]`, a gate card; nothing before approval. There is no T1 path |
| Consent revoked mid-flight | `broker.disconnect(owner, "meeting_host")` after approval, before dispatch: the dispatch makes no request (`NotConnected`, no attempt spent); MTG09-b's disconnect handler abandons the unsent entry (`failed`, no `data.transfer`, no receipt); reconnecting later sends nothing for it. An entry still unsent at `draft.start` is refused (MH-12) |
| Calendar write from the sync path | `adapters/calendar.py` and `calendar_sync.py` hold no `"POST"`, `"PUT"`, `"PATCH"` or `"DELETE"` literal and never name `CALENDAR_EVENTS_OWNED` or `meeting_host`; a sync run against the fake records GETs only, with `(u, "google_calendar", (CALENDAR_READONLY,))` asked of the broker; `load_calendar_sync_config` still refuses a writable `google_calendar` (existing test). Only `adapters/meeting_host.py` and `meeting_host.py` contain `calendar.events` |
| Link and addresses in logs or events | FR-MTG-09 (c). Also `repr()` of a draft, receipt and adapter shows no title, address or token |
| Grants of two accounts | Owner has `gmail` and `meeting_host`: `disconnect(owner, "gmail")` revokes the Gmail grant at Google (one revoke call); `disconnect(owner, "meeting_host")` revokes only the host grant. With `gmail` and `google_calendar` connected, disconnecting one still skips the revoke (CON-D10 unchanged). MH-C1: a callback whose `scope` includes `gmail.readonly` raises `ConsentRefused`, stores nothing and revokes nothing |
| Tokens and passwords | No token in any part, log or exception (existing broker tests extended to `meeting_host`); no password field or parameter anywhere |

## Dev and CI

Fakes and recordings only (EFF-01): `_meeting_host_lib.FakeHostCalendar` implements `Transport` for
`POST /calendar/v3/calendars/primary/events` and `GET .../events/{id}`. It keeps events by id, answers 409 for
a known id, counts invitations per event (one per attendee, only on the first successful insert with
`sendUpdates=all`), and can be scripted to lose an answer after creating (`TransportError`), answer 401 once,
400, 403, 404, 429 or 500, or report `pending`, `success` or `failure`. It never opens a socket; tests patch
`socket.socket`, `socket.create_connection` and `socket.getaddrinfo` to raise. No real invitation is ever sent
from dev or CI; the Calendar API is free, but the rule is no live call without `LIVE=1`, set by the user only.

## First live step (the user only)

1. Confirm ADR-0024 (or choose the Owner's own calendar instead, BQ-MTG09-2).
2. Use a bot Google account that nothing else uses, with 2-step verification on (the meet-bot's existing bot
   account qualifies if that holds). Tilo and its agents never ask for its password.
3. Google Cloud console, OAuth consent screen (Testing): on Data Access add
   `https://www.googleapis.com/auth/calendar.events.owned`; on Audience add the bot account as a test user;
   enable the Google Calendar API if it is not enabled yet.
4. After MTG09-a merges: `LIVE=1` plus `GOOGLE_OAUTH_*`, then `uv run python
   services/connectors/scripts/live_meeting_host_smoke.py --invite <your own test address> --start-in-min 30`
   (modelled on `live_gmail_smoke.py`): your browser opens Google's consent page, you sign in **as the bot**,
   the script creates one event and prints the conference status and event id (never the link). Check the
   invitation in the test inbox.
5. After MTG09-b and -c: host a test meeting from S-26 with two test accounts you own, approve the card, start
   the bot container by hand at meeting time, sign the bot in through noVNC, join with the link from your own
   invitation, then remove the container. Notes go into the report (FR-MTG-09 (e)).

## Builder notes and ticket split

- MTG09-a (CL-REACH: `services/connectors`, `config/`): `meeting_host.py`, `adapters/meeting_host.py`, grant
  groups and MH-C1, `MeetingHostConfigError`/`MeetingHostRefused`, the three config edits, the fake, the smoke
  script. Security review (token broker, T3, outbox). Orchestrator or user regenerates B-007 after the config
  change. `services/connectors/CLAUDE.md` is at its 40-line cap: extend lines (Purpose, Config, Requirement
  IDs), add none.
- MTG09-b (CL-PEOPLE, CL-INT: `services/api`, `apps/web` S-26 button): the route (404 for non-owners, 409 for
  a meeting not `scheduled`/`bot` or already hosted, 422 with the MH rule id), the fixed plan, `Run.gate()`
  seams (resolver as step 5; `exact` from `draft.exact` for this action instead of `_exact`, whose
  address list would hit the 500 limit), abandon on `meeting_host` disconnect, the `needs_you` card on
  `conference: failure`.
- MTG09-c (MEET lane, `meet-bot/` on its own branch): ADR-0024 bot rules (host join, admit nobody, tmpfs
  profile, link never written to `out/`, logs or the package).
- PPL-60c (later): `MeetingHostAdapter.join_link(owner: str, receipt: HostReceipt) -> str` (a read with
  `fields: "status,hangoutLink"`; MH-20 a cancelled event, MH-21 a link that does not fullmatch
  `https://meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}`); the string lives in memory for the bot's start
  request only. Until then no module may call it.
