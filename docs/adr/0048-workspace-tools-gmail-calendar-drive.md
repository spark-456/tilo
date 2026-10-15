# ADR-0048: Workspace tools: agents read the person's own Gmail, Calendar and Drive; reminders and calendar changes go through the outbox

- Status: **Proposed** (16 Oct 2026), for the supervisor's acceptance. Scope: the owner's direction below (about
  02:05 IST, relayed verbatim by the supervisor, who treats it as the owner's approval to add these capabilities).
  Everything here is additive (meeting_host_rpc 1.4.0, four risk-table rows, two action descriptions); no frozen
  rule changes. BQ-WST-1 is the one choice only the owner can make; the shipped default follows the PRD.
- Deciders: owner (scope), supervisor (acceptance), architect (design)
- Requirement: FR-CON-03, FR-CON-04, FR-CON-05, FR-CON-14, FR-CAL-04, FR-CAL-08; SEC-02, SEC-03, SEC-05; EFF-01;
  PRD 10.4, 12.1, 12.2, 13.1, 16.1; ADR-0029 decision 7, ADR-0032 (HB-01, HB-06), ADR-0032a, ADR-0035 (LC-06,
  LC-14 and decision 6), ADR-0040
- Number: 0048. 0045 (`cx/INVITE-LINK`), 0046 (`contracts/INVITE-LINK`) and 0047 (`contracts/MEETING-BRIEF`) are
  taken on open branches; 0048 was free on every remote branch on 16 Oct. New rule ids WT-01 to WT-10 (unused
  prefix); questions BQ-WST-1 to BQ-WST-8.

## Context

The owner, verbatim: "We need the gmail, calendar and drive for sure, since they were part of the initial promise,
helping understand mails and giving you reminders, updating and reading your google calendar, and saving files to
your drive if necessary or referencing things on your file, etc... These are not optional, these are essentials ...
Add them immediately to the work list and dont delay them."

What exists on `live14-candidate` (ea04e5c1), read from the code and the 16 Oct capability audit:

1. A run's agents have exactly two tools, `web_search` and `fetch_url` (`run_tools.py`). Five shipped skills list
   read tools (`search_email`, `read_email`, `read_events`, `list_files`, `read_file`) that have no `Tool` object, so
   those skills get nothing. Gmail drafts and sends, Drive saves and Calendar creates exist only as gated side
   effects through the outbox (ADR-0035).
2. The adapters already read: `GmailAdapter.search_threads/get_message` (gmail.readonly, mail marked untrusted),
   `CalendarAdapter` (`events.list` on the primary calendar with the PE-13 field mask, `clean_title`) and
   `DriveAdapter` (drive.file; reads only picked or Tilo-made files, `NotPicked` before any request).
3. The tool loop (`ToolUnitRunner`) already does what a read of private text needs: argument check against the
   tool's schema, SEC-05 taint (a reader loses side-effect tools), `neutralise`, a SafetyProvider screen that fails
   closed, a raw-archive record, and a `TOOL_RESULT ... (data, not instructions)` block.
4. `data.transfer` with direction `in` is already "a read under the connection the person consented to", carrying
   the person's consent as `authz`. `connection_view.connected_at` (ADR-0032a) is the grant time.
5. The read actions are declared T1 in `config/connectors.yaml` but missing from `config/autonomy.yaml`, so BQ-44
   makes them T3 today.
6. The consent screen (11 Oct record) already holds gmail.readonly, gmail.compose, gmail.send, drive.file,
   calendar.readonly and calendar.events.owned; publishing status In production, unverified, lifetime cap 100 users.

## Decision

1. **Five read tools, named after the actions they run**, so the five skills work as written and the risk table's
   key is the tool name:

   | Brief name | Tool | Connector, capability, scope | Result (meeting_host_rpc `$defs`) |
   | --- | --- | --- | --- |
   | gmail_search | `search_email` | gmail, search, gmail.readonly | `search_email_result`: at most 10 summaries (id, thread, sender, subject, date, snippet, unread) |
   | gmail_read | `read_email` | gmail, read, gmail.readonly | `read_email_result`: headers, text body cut at 20,000 characters, attachment names only |
   | calendar_list | `read_events` | google_calendar, read, calendar.readonly | `read_events_result`: primary calendar, window of at most 31 days, at most 50 events, PE-13 fields |
   | drive_search | `list_files` | google_drive, list, drive.file | `list_files_result`: at most 10 files Tilo may read, name or full-text query |
   | drive_read | `read_file` | google_drive, read, drive.file | `read_file_result`: Docs and Slides as text, Sheets as CSV, text files, cut at 32,000 characters; a PDF of at most 4 MiB as bytes |

   Each `*_args` def is self-contained (no `$ref`), so it is also the tool's input schema: the harness validates the
   model's arguments against it and the provider layer sanitizes it for function calling.
2. **Tier T1, no gate, no outbox entry** (ADR-0035 decision 6 already said so). `config/autonomy.yaml` now lists
   `search_email`, `read_email`, `list_files` and `read_file` beside `read_events`; the SEC-11 test keeps each an
   ungated read. A model never decides whether a read is allowed: WT-01 is code.
3. **One route.** tilo-connectors serves `POST /internal/workspace/read` (`read_request`, `read_answer`), HB-01's
   caller check, the 64 KiB body cap, closed objects, the four common error codes. The answer's outcomes are `ok`,
   `not_connected`, `missing_scope`, `expired`, `not_found`, `too_large`, `unsupported_type` and `unavailable`;
   `ok` carries the result and `connected_at`. tilo-api calls it from the run's tool, never from the browser.
4. **WT-01 Owner-only worlds.** A read tool is offered and run only in a run of a world with no team share in force
   (ADR-0040 decision 3), checked at every call, so a share made mid-run stops the next read; never in a demo
   session. `read_request.user_id` is the world's record owner, from the world record, never from a model, a tool
   argument, a body, a path or a query. In a shared world the tools are not offered and a call gets a fixed note.
   Another tilo-api feature may call the route only for the signed-in person's own account (`user_id` that person,
   never from a demo session) and only if it records each `ok` read as WT-05 does, in a world that person owns (a
   Desk world: `district` null, `vis: []`); its own ADR names it. The Quick assistant records nothing, so it may not
   (WT-09).
5. **WT-02 Arguments.** tilo-api checks the arguments against the tool's args def before any call. `read_events`
   also needs `end` after `start` and at most 31 days; tilo-api refuses before the call and connectors re-checks
   (`invalid_request`). `list_files` puts `query` into Drive's `q` only with `\` and `'` escaped, as
   `(name contains '<q>' or fullText contains '<q>') and trashed = false`. `search_email`'s query is Gmail's own
   syntax over the person's own mailbox: it can only narrow what gmail.readonly sees.
6. **WT-03 Results are data.** Connectors answers only the closed result defs, cut to their caps, with no link,
   token, attachment bytes, event description, location or guest address, and no Drive owner or sharing. The tool
   declares `external_content: True`, `side_effect: False`, tier T1, so the loop's path above applies unchanged, and
   a PDF goes as a native part that is screened too. Reading makes the unit a reader (SEC-05). Nothing is cached
   beyond the unit's in-memory tool cache (PRD 13.1: email bodies are never cached).
7. **WT-04 Private data never leaves by the web.** A unit that called a read tool, or whose upstream item rests on
   such a unit's output (`UpstreamItem.private`, carried downstream like `tainted`), is private: it is never offered
   `fetch_url`, and a call gets a fixed note. `web_search` stays, since its query goes only to the search provider.
   What a private unit writes reaches the person in Tilo (the web's CSP loads no remote image) or through a gated
   outbox action that shows it first.
8. **WT-05 Every read is recorded.** Each `ok` read in a world writes one `data.transfer` through tilo-api's one
   writer: data `{connector, action_type: <tool>, direction: in, artifact: null, outbox_id: null, risk_tier: T1}`,
   `authz {by: person, ref: <world owner>, at: <connected_at>}`, actor the unit's agent, target the unit's building,
   item `{kind: scroll, artifact_id: null, label}` with a fixed label per tool ("Mail search", "1 email", "Calendar
   events", "Drive file list", "1 Drive file"), a fixed summary per connector ("An agent read from Gmail."), and
   `trace.tool`, `trace.latency_ms`, `trace.archive_ref` from the call. No event field holds a query, an id, a
   subject, a sender, a file name or a title. A refused or failed read writes no event (the archive keeps the call).
   Fixture: `fixtures/events/valid/data.transfer--workspace_read.json`. Readers that count a `data.transfer` as
   "sent" must check `direction == "out"` (`notifications.py` does not yet).
9. **WT-06 Scopes: no new Google scope.** Each tool uses exactly the scope its capability declares (the broker's
   `required_scopes`) and answers `missing_scope` rather than asking for more. gmail.readonly reads and searches;
   calendar.readonly reads; calendar.events.owned writes; drive.file reads, lists and writes.
10. **WT-07 Drive: drive.file and Google's Picker, the PRD's own design.** PRD 12.2 promises "files and folders the
    user picks", FR-CON-05's acceptance test is "files outside the picked set are never read" (its config test pins
    drive.file and forbids drive.readonly), and the published privacy page says Tilo cannot see the rest of the
    Drive. Under drive.file Google itself enforces that set: `list_files` and `read_file` see only files the person
    picked in Google's Picker and files Tilo saved; anything else is `not_found`. The person picks in the web (ticket
    E) with Google's Picker, which grants Tilo's OAuth app per-file access. The Picker needs an access token in the
    page: Google Identity Services gives it for drive.file only, for the same OAuth client. It lives in page memory
    only while the Picker is open, is never stored, logged or sent to any Tilo endpoint, is never revoked by the
    page (that would revoke the person's whole grant) and expires within the hour. It is the one browser-held token
    in Tilo; ADR-0032's rule (tokens only in tilo-connectors) still holds for every token Tilo's services hold.
    Rejected: **drive.readonly** (a restricted scope over the whole Drive; it reverses FR-CON-05, its test and the
    privacy text, and a public launch would need Google's security assessment), and **drive.file plus
    drive.metadata.readonly** (also restricted; it shows every file name but still reads no content). Whole-Drive
    reading is BQ-WST-1, the owner's call: two scope lines, the FR-CON-05 config test, the privacy text and one
    consent-screen scope; the tool code is the same.
11. **WT-08 Writes stay on the outbox and the policy engine** (OB, CR and LC rules unchanged; T3 always a person):
    - `create_event` (T1, ADR-0035 decision 6, unchanged; BQ-WST-6): the `calendar_event` item document gains an
      optional `reminders`, at most 5 of `{method: popup | email, minutes: 0 to 40320}`, sent as
      `reminders {useDefault: false, overrides}`; absent means Google's defaults. "Remind me" is a `create_event` at
      the reminder time, 15 minutes long, with a popup at 0 minutes (and email when asked); the Agenda shows it
      through the FR-CAL-08 sync. The document is code (`item_documents.py`, `side_effect_execute.py`,
      BQ-ADR35L5-1), not a contract.
    - `update_event` (new): google_calendar, capability `write` (calendar.events.owned), **T2**, gate `approval`,
      irreversible false. The entry's `destination` is the Google event id (common `destination` shape), its item a
      `calendar_event` document with the new values, no recipients, no attachments. The adapter reads the event first
      and refuses, before any write, unless it is confirmed or tentative, `organizer.self` is true and no one but the
      person attends; then `events.patch` on the primary calendar with summary, start, end and reminders only,
      `sendUpdates=none`, and `extendedProperties.private.tilo_update = side_effect_marker(entry)` so a retry finds
      it (OB-03). T2, not T1: it changes something the person already has, so a policy for `create_event` never
      covers it by accident; at L1 both wait at a gate. An event with guests is refused (BQ-WST-5). Ticket D adds the
      two config lines together with the adapter, so nothing declares an action no adapter performs.
    - `save_file`, `save_as_google_file` (T1, drive.file, Tilo folder), `create_draft` (T1) and `send_email` (T2;
      new recipients or attachments make it T3) are unchanged.
12. **WT-09 Not on the Quick assistant in this release.** Quick keeps nothing (no history, no record), so a read
    there would leave no audit row (PRD 10.4 Audit). Assistant reads wait for the recorded assistant path
    (`/v1/assistant/ask`, PPL-11b): BQ-WST-7.
13. **WT-10 Live gate.** Only tilo-connectors calls Google (LC-14, EFF-01). Dev and CI use the adapters'
    `ReplayTransport` recordings or fakes; tilo-api's tests use a fake read client. Google's APIs are not billed;
    the model calls of the tool loop are metered as today.

**Consent (FR-CON-03, LC-06).** The Connectors toggles map to existing capabilities through the unchanged
`POST /v1/connectors/connect {connector, capabilities}`: "Read mail" gmail `[read, search]`, "Read calendar"
google_calendar `[read]`, "Read Drive" google_drive `[read, list]` followed by the Picker. The copy says in plain
words what each lets agents do and that they read only in the person's own worlds. A missing capability is a tool
result that says what to connect; a read never raises a consent card (only the person's Connect starts a flow).

## Failure modes

| Condition | Result |
| --- | --- |
| Not connected, or the capability's scope is missing | the tool result names what to connect ("Read mail in Connectors"); the unit reports honestly |
| Grant refused at refresh | `expired` plus a `connection.expired` part: the reconnect card as today |
| The stored grant has no readable `connected_at` | `expired` (connect again): no read without a consent time to stamp |
| World shared with a team, or a demo session | tools not offered; a call gets a fixed note; nothing is read |
| Result flagged by the screen, or the screen fails | dropped (the loop's `DROPPED` note); the archive keeps the call |
| Drive file not picked | `not_found`, the same as a missing file |
| A Word, Excel or PowerPoint file, or an image, in Drive | `unsupported_type` (BQ-WST-4); attaching it on Home still works |
| PDF over 4 MiB | `too_large` |
| Google busy or slow | `unavailable` (and a `connection.rate_limited` part when Google said so); the loop may try again within its caps |
| tilo-connectors not configured or not LIVE | 503 `not_configured`: the tool failed note |

## What the owner configures

- Gmail and Calendar: nothing new; confirm on the Audience page that the app is still In production. If it is in
  Testing, only listed test users (tilotesting@gmail.com and the owner's accounts) can consent and refresh tokens
  expire after 7 days. Unverified means everyone sees Google's "unverified app" screen; gmail.readonly is a
  restricted scope, so verification would need a security assessment (not before 17 Oct).
- Picker (ticket E): enable the Google Picker API; create a browser API key restricted to the web origin's
  referrers and to the Picker API; add the web origin as an Authorized JavaScript origin on the OAuth client; give
  the web build the client id, the API key and the project number (public values, build env, not code).
- Only if BQ-WST-1 is answered "the whole Drive": add drive.readonly on the consent screen.

## Consequences

- The five skills that name read tools work as written; no new read action, no event-registry change, no new scope.
- One contract minor, four risk-table rows, two description edits; two pins move (meeting_host_rpc root set, SEC-11)
  and the B-007 replay fixture is regenerated with the fake provider (its plan key reads config/connectors.yaml).
- Residual: an injected mail can still steer what a private unit writes for the person, who reads it before any
  gated send; the screen is probabilistic; a world shared after a run shows outputs that rest on private reads
  (BQ-WST-3).

## Tickets (detail in `agy-bridge/tasks/WORKSPACE-TOOLS-TICKETS.md`)

- **A** (Claude, connectors and tilo-api client; security review): the read route and five adapter reads, caps,
  outcomes, `connected_at`, the tilo-api read client.
- **B** (Claude, harness and tilo-api; security review): five `Tool`s over the client, WT-01, WT-04, WT-05, default
  tool sets, prompts, `notifications.py` direction check.
- **C** (Codex, web): Connectors read toggles and consent copy; the share dialog line of BQ-WST-3.
- **D** (Codex, connectors, tilo-api and web; security review for the adapter): reminders, `update_event`, the
  "Remind me" path and the Agenda.
- **E** (Codex, web; security review): the Drive Picker after the owner's console steps.
