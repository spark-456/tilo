# PPL-11c: the rest of the people API on tilo-api (what the acceptance tests pin)

> **Status.** Written by the test-writer on `tests/PPL-11c-people-api-rest` from `origin/phase0-stack` (after PPL-11a A quotes
> #458, B plate #463, C confirms and creates #466). Every PPL-11c test is a strict xfail until its slice lands
> (`SLICE_PENDING` in `_ppl11c_lib.py`, applied by `conftest.py`); `test_PPL_11c_guards.py` passes today and is never pending.
> The names below are chosen by the test-writer; a builder may change one if it says so and edits the tests in the same PR.

Source: `docs/prd-addendum-people-agents.md` (FR-MTG-10, FR-PA-01, FR-PA-03, FR-PB-01), `contracts/people.rules.md` PE-02,
PE-03, PE-05, PE-07, PE-08, PE-12, PE-13, PE-16, PE-17, PE-19, PE-22, PE-23, PE-24, PE-29, PE-30, ADR-0015/16/17/20/21,
`docs/open-questions.md` BQ-265..273, BQ-CCP3-*, BQ-PPL10-*, `API_PPL_11a.md`, `API_SEC_15.md`, and the follow-ups of
issues #456, #462 and #464 (and the #470 review comment on `email`). Built on `packages/people` (`decide`, `check_write`,
`Directory`, the stores, `delete_meeting`/`meeting_tombstone`, `resolve_due`) and PPL-11a's `Writer`, `json_body`,
`Refusal`, `_PeopleRoute`. Fakes only: in-memory people stores, an in-memory `ArtifactStore`, a stamping fake event writer,
fake Desk worlds and a fake meeting-world maker (`_ppl11a_lib.Rig`, extended here with those three seams). No network, no
paid call, no model id, no secret (the fake token is assembled at run time).

PPL-11b (pins, mentions, calendar, assistant, free/busy) is untouched. Everything here sits behind the SEC-15 gate (no new
public route), leaves the SEC-16 seams alone, makes no model call, builds no router and reads neither `replay_only` nor
`LIVE` nor `TILO_JUDGE_LIVE`; the static scan of `tilo_api/people*.py` (`test_PPL_11a_gate_seams_and_dev.py`) still applies to
every new module.

## 0. Size and suggested split (about 850 hand-written lines in all; each slice is far under 400 and green on its own)

A throw-away spike (never pushed) made every test in this ticket pass, which shows the interface is consistent and the tests
are satisfiable: about 830 lines, of which route boilerplate is 250. Per slice, roughly:

| Slice | What | Test file | Needs | About |
| --- | --- | --- | --- | --- |
| **S2a** (do first) | `POST /v1/meetings/{id}/delete` removes transcript, minutes and proposed derived records, tombstone last; confirm refuses a gone source; item-quote gone path needs the owner match | `test_PPL_11c_s2a_meeting_delete_and_derived_data.py` | none | 120 |
| **S1** | work-item list, get, edit, done, snooze, reopen, not-mine | `test_PPL_11c_s1_work_items.py` | none | 200 |
| **S1b** | put back | `test_PPL_11c_s1b_work_item_put_back.py` | S1 | 20 |
| **S2b** | meeting get, edit, the minutes read | `test_PPL_11c_s2b_meeting_get_edit_minutes.py` | none | 130 |
| **S3** | first person, email rules and uniqueness, memberships, roles | `test_PPL_11c_s3_directory.py` | none | 160 |
| **S4** | body cap, idempotency key, rate cap, no whole-org listing on writes, no-store everywhere, dev CORS | `test_PPL_11c_s4_write_limits.py` | S1, S1b, S2a, S2b, S3, S6 (the body-cap test lists every route; the first-person retry test needs S3) | 110 |
| **S5** | PE-12 events (`work_item.created`, `work_item.changed`), Desk worlds | `test_PPL_11c_s5_work_item_events.py` | S1, S1b, S3; S4 for one test; ADR-0009 contract change for the dev test (it skips until then) | 80 |
| **S6** | `meeting.world_id` | `test_PPL_11c_s6_meeting_world.py` | none; a one-row addition to `tilo_people.writes` | 40 |

**Gating (the answer to "how do I gate them").** One tuple, `SLICE_PENDING` in `_ppl11c_lib.py`, one entry per file
(`test_PPL_11c_s1_`, `test_PPL_11c_s1b_`, `test_PPL_11c_s2a_`, ...). `conftest.py` marks every node id that contains an
entry `xfail(strict=True)`. A slice's builder deletes its own entry in the same PR; leaving it makes the now-passing tests
XPASS(strict), which fails. Files are split per slice, so a builder never touches another slice's tests. To see the real
failures: `uv run pytest services/api/tests/test_PPL_11c_s1_work_items.py --runxfail -q`. S4's body-cap test and S5 name
routes of other slices, so S4 and S5 go last (or their route lists shrink in the same PR, saying so). Suggested PRs: (1)
S2a alone (security), (2) S1+S1b, (3) S2b+S6, (4) S3, (5) S4, (6) S5. S5 adds `deps.get_desk_worlds` and the dev wiring;
S6 adds `deps.get_meeting_worlds`. Both seams default to 503 `not_configured`.

`PENDING_EXEMPT` (same module, applied by `conftest.py`) lists tests inside a pending file that already pass once an earlier
slice lands (today `test_PPL_11c_s5_HR_1_a_refused_...`, a negative test that S1's routes satisfy): they run, they are not
xfail. The S5 builder deletes that entry in the PR that removes `test_PPL_11c_s5_` from `SLICE_PENDING`.

`services/api/CLAUDE.md` has a 40-line cap that builders keep breaking: run `tests/repo` before pushing.

## 1. Routes (all behind the SEC-15 gate, all `Cache-Control: no-store`, all JSON only)

Methods stay GET and POST (dev CORS allows only GET, POST, OPTIONS; PATCH and DELETE would need a CORS change for no gain).
Path parameter names are pinned (`require_route` reads the OpenAPI document): `{work_item_id}`, `{meeting_id}`, `{person_id}`.

| Route | Who | 200 body | Refusals (besides 401, SEC-15 403, 413, 415, 422, 429, 503) |
| --- | --- | --- | --- |
| `GET /v1/work-items?status=` | the person | `{"items": [full record, ...], "truncated": bool}` | 404 no person record; 422 bad `status` |
| `GET /v1/work-items/{id}` | owner (full record), assigner of a confirmed item (status view) | record or `{id, title, status, due}` | 404 |
| `POST /v1/work-items/{id}/edit` | owner | the stored record | 404, 409 |
| `POST /v1/work-items/{id}/done`, `/snooze`, `/reopen`, `/not-mine`, `/put-back` | owner | the stored record | 404, 409 |
| `GET /v1/meetings/{id}` | owner | the stored meeting | 404 |
| `POST /v1/meetings/{id}/edit` | owner | the stored meeting | 404, 409 |
| `POST /v1/meetings/{id}/delete` | owner | `{"id", "status": "deleted"}` | 404, 409, 503 |
| `GET /v1/meetings/{id}/minutes` | owner | the minutes document (`minutes.schema.json`) | 404, 503 |
| `POST /v1/meetings/{id}/world` | owner | the stored meeting | 404, 409, 503 |
| `POST /v1/people/first` | the signed-in principal | membership view (201) | 403, 409 `email_taken` |
| `POST /v1/people/{id}/memberships`, `/memberships/remove` | org owner | membership view | 404, 409 |
| `POST /v1/people/{id}/role` | org owner | membership view | 404, 409 |

As in PPL-11a: **a refused read or write of an existing-or-not record is one byte-identical 404 whatever the cause**
(unknown, malformed, other org's id, not yours, wrong state, no person record, a proposed item, a deleted meeting for a
non-owner); a refused create is 403 with no reason; 422 for a bad shape (shape and schema before authorisation, so no
oracle; the body of a 422 never echoes a key or value the caller sent); 409 `{"detail": "version_conflict", "code":
"version_conflict"}` after exactly one compare-and-set attempt, or 409 `{"detail": "write_refused", "code": "write_refused",
"problems": [<check_write codes>]}` for a state the MAY row refuses; 503 `{"detail": "not_configured"}` for an unwired seam
and `{"detail": "unavailable"}` for a store or source that cannot be read, never a 500 and never a partial answer. Bodies
are closed (`extra=forbid`): **no id, org, owner, stamp, status, source, `source.ref`, evidence, history, world or `due`
ever comes from a request body.** Text is cleaned (`clean_line`), then redacted (`deps.get_redactor`), then schema-checked
(`Writer.text`, #470).

## 2. Work items (PE-03, PE-07, PE-19, PE-29, PE-30, FR-PA-01, FR-PA-03)

* **List.** The caller's own `open|done|dropped` items they may read in full (never `proposed`, never an item of someone
  else, never one with a history over `MAX_HISTORY`), full records, ordered by `due` ascending (none last), then
  `created_at`, then `id`; at most 200 (`truncated` when more exist); `?status=open|done|dropped` filters, anything else
  is 422. Reads the owner index (`work_items.list(org, "owner", user)`), never `persons.list`.
* **Get.** Owner: the full record. The assigner of an item that is no longer `proposed`: the `status` view only (PE-03).
  Nobody else, and nobody at all for a `proposed` item (the assigner confirms it, she does not read it): the one 404.
* **Edit** `{title?, due_text?}`, at least one, nothing else (a `source`, `source.ref`, `status`, `owner`, `assigned_by`,
  `created_by`, `confirmed_by`, `history`, `due`, `flagged`, `snoozed_until`, `evidence`, `id`, `org_id` or stamp is a 422).
  `due` is `resolve_due(due_text, meeting_at=now, time_zone=<the caller's>)`, as on create; `due_text: null` clears both.
  One history entry `edited`.
* **done** (`open` to `done`, history `done`), **snooze** `{until}` (timestamp with three fractional digits; later than now
  and at most 30 days after it, else 409 `snooze_range`; a malformed timestamp is 422; history `snoozed`), **reopen**
  (`done` to `open`, history `reopened`, 409 otherwise), **not-mine** (only for an item someone else assigned and not
  already asked: history `reassign_requested`, status stays `open`, the item moves to `parked.asked`; 409 with non-empty
  `problems` otherwise), **put-back** (a snoozed item gets `snoozed_until` null, an asked item is simply released; history
  `edited` either way; 409 for an item that is not parked; a done item is put back with reopen). The five action routes take
  `{}` (snooze: `{until}`) and nothing else.
* **Authorisation comes before the record's own schema check**: a request for an item the caller may not touch is the one
  404 even when the record it would produce is schema-invalid (a Tilo-made `done` item needs `confirmed_by`); 422 is for what
  the caller's own text and numbers got wrong.
* Every write: `decide`, then the record rebuilt from the stored one plus `updated_at = now` and exactly one history entry
  `{at: now, by: actor, change, status}`, `check_write`, compare-and-set. A second `done` on a done item is 404 or 409 and
  changes nothing. A success moves exactly one version; a refusal moves none.
* A write reads at most two person records and never lists the org (section 7).

## 3. Meetings (FR-MTG-10, PE-05, PE-07, PE-13, PE-16, PE-19, PE-22 to PE-24)

* **Delete** (S2a). Order: transcript and minutes artifacts removed through the artifact store (every blob generation and
  record, the meeting's own `Scope`; the existing FR-MEM-09 adapter `ArtifactStore.retention().delete(record_path)` with
  `orgs/<org>/worlds/<world>/artifacts/<artifact>/versions/<six digits>` does it), then the *proposed* work items, pins and calendar entries whose `source.ref` is the
  meeting or an action item of it (`mt_x`, `mt_x#aiN`) removed from their stores, then `meeting_tombstone` by compare-and-set
  (the last step). It needs the artifact store: unwired, every caller gets 503 `not_configured` and nothing changes (no
  oracle). A failing artifact store is 503 `unavailable`, the meeting still live, every record still there; the same call
  then succeeds. A lost compare-and-set at the end is 409, and the retry completes (every step is idempotent). A second
  delete by the owner is 200 with the same body and no new version. What the owner already released (a confirmed item, an
  accepted entry, an active pin) stays the assignee's, readable, its quote `expired` (PE-23, BQ-PPL10-2). Discarded and
  never-started meetings can be deleted too. Body `{}` only.
* **Confirm refuses a gone source** (#464). `POST /v1/work-items/{id}/confirm` of a proposed item whose meeting is
  `discarded` or `deleted` (record or tombstone) is the one 404, even when the proposed item itself was never swept.
* **Quote gone path** (#456). `GET /v1/work-items/{id}/quote` answers `expired` for a discarded or deleted meeting (and
  `expired` for a *missing* meeting, as today) only when the item's `assigned_by.by` equals the meeting's `owner` on the
  record or tombstone; otherwise the one 404. (The oracle in `tests/contracts` needs the same line, with an invalid case.)
* **Get.** Owner: the stored meeting (a `discarded` one too). Everyone else, an unknown id and a `deleted` meeting (for
  everyone, the owner included: the content is gone, the quotes route still answers `expired`): the one 404.
* **Edit** `{title?, series?, scheduled?, agenda?, attendees?: [{name}]}`, at least one, nothing else (`source`, `status`,
  `owner`, `world_id`, `attestation`, `transcript`, `minutes`, `minutes_confirmed_by`, `delete_*`, `ended_reason`, `id`,
  `org_id`, `created_at`, an attendee `user` and any nested extra are 422). Text cleaned and redacted; a link in a title,
  agenda title or attendee name is 422 (PE-13). `attendees`: a name that was already there keeps its resolved `user`, a new
  name gets null (a request never sets identity, PE-15). A `discarded` or `deleted` meeting is not editable (404). The
  version moves by one; nothing else of the stored meeting changes.
* **Minutes** `GET /v1/meetings/{id}/minutes`. The owner, of a meeting that is `minuted`, has a `world_id`, has a
  `minutes` reference and is before `delete_minutes_after` (`now >= it` is 404), reads the minutes document through the
  artifact store in the meeting's own `Scope`, with every string cleaned and redacted; they may read it before they confirm
  it. Minutes that name another meeting, a version not in that scope, or no meeting: 404; a corrupt document: 503. Needs the
  artifact store and the redactor (unwired: 503 for everyone). It writes nothing and the answer is `no-store`.

## 4. The directory (PE-17, PE-19, PE-20, PE-09)

* **First person** `POST /v1/people/first {display_name, aliases, email, time_zone, preferred_channel}`: allowed only when
  `deps.ORG_ID` has no person and the principal has no record; the record is `id` = the principal's id, `org_id` =
  `deps.ORG_ID`, `org_role` owner, no memberships, `created_by` = {principal, now}; answer 201 membership view; otherwise
  403. Two principals racing for an empty org: one 201, the rest 403 (one atomic create-if-the-org-is-empty). It sits
  outside `decide` (BQ-PPL10-3: "minted by tilo-api"). Org, role, id and stamp are 422 in the body.
* **Email.** On `POST /v1/people` and `/first`: an ASCII dot-atom address or 422 (never echoed): before the `@`, letters,
  digits and `. _ % + - '` with no leading, trailing or doubled dot; after it, dotted labels of letters, digits and hyphens
  (63 at most, none starting or ending with a hyphen), at least two, the last letters only and two or more; 254 at most.
  No control, format, invisible, non-ASCII, space, quote, bracket, backslash or other punctuation. Unique within
  `deps.ORG_ID`, compared case-insensitively over the whole address: 409 `{"detail": "email_taken", "code": "email_taken"}`;
  one winner when callers race. The stored value is as typed. Another org's address is not a clash (one org is served).
* **Memberships** `{team}` (`^tm_[0-9a-z_]{1,48}$`): add stamps `assigned_by` = {actor, now}; adding a team the person is
  already in is 200 with no new version; the ninth team is 409 `write_refused` with `schema`. An org owner may add
  themselves; a member may add nobody (404). Remove: 200, absent team 200 unchanged. Response: membership view
  `{id, display_name, org_role, memberships}`. Teammate-ness changes at once (the directory is re-read per request).
* **Role** `{org_role: "owner"|"member"}`: member to owner only (`check_write` `transition` otherwise, so owner to owner,
  member to member and demotion are 409); a member cannot promote themselves (404); a promoted owner may create people.
* A principal is bound to exactly one person record: `first` is refused for a principal with a record, emails are unique,
  ids are minted per call (PPL-11a). Everyone but an org owner gets the one 404 on memberships and roles.

## 5. Events and Desk worlds (PE-12, PE-30; S5)

Only the registry's `work_item.created` and `work_item.changed` (both registered and fixtured: guard test). Meeting,
person, membership and role writes emit nothing (no registry type; `meeting.minuted` is the analyst's) and work with the
event seams unwired.

| Write | Event | World | actor / target |
| --- | --- | --- | --- |
| create item (person-made) | `work_item.created` data `{work_item_id, owner, status: open, source_kind}` | the owner's Desk world | the caller / the owner |
| edit, snooze, done, reopen, not-mine, put-back | `work_item.changed` data `{work_item_id, change, status}`, `change` = the history entry the write added (`edited, snoozed, done, reopened, reassign_requested`; put-back is `edited`) | the owner's Desk world | the caller / the owner |
| confirm (PPL-11a route) | `work_item.changed` `confirmed`, status `open` | **the assignee's** Desk world (PE-12 "confirmed for P") | the confirmer / the assignee |

A part carries its own ULID `id`, `type`, `actor`, `target`, `summary` (at most 140 characters; display names and counts at
most: no title, due phrase, quote, address or link), `vis: []` (owner-only; `district` null), `authz` null, closed `data`;
the writer stamps the rest. Seams: `deps.get_event_writer()` (existing; production 503) and **`deps.get_desk_worlds()` ->
object with `desk_world(org_id: str, user_id: str) -> str`**, idempotent, creates the person's one Desk world lazily
(`w_desk_<user id without "u_">`); production default 503 `not_configured`; dev mode wires one over its `Store`
(`WorldRecord(owner=user, districts={})`), so `DevEventWriter` accepts the event. Order: refuse first (no event, no world),
then commit, then resolve the Desk world and append once; a failed append or Desk world undoes the write by compare-and-set
(a created record is deleted) and answers 503 (content restored; the version may move twice), so no row looks changed without its event (HR-1, PE-30). A lost compare-and-set
writes nothing. Unwired event writer or Desk worlds: every work-item write is 503 `not_configured` and commits nothing.
**Needs contract change (accepted ADR-0009, architect PR still to land; the dev-mode test skips until it does):** `event.schema.json` `district_list` has
`minItems: 1`, so `vis: []` fails the schema and the dev writer's validation. The tests assert `vis == []` and validate the
event with `vis` widened to `"all"` until then; the dev-mode test stays red until the contract change merges.

## 6. `meeting.world_id` (BQ-273; S6)

`POST /v1/meetings/{id}/world` `{}`, owner only, a meeting that is not `discarded` or `deleted`: if it has a `world_id`,
200 unchanged (the maker is not asked); else `deps.get_meeting_worlds().make_meeting_world(org_id=, owner=, meeting_id=)`
(idempotent per meeting; production 503 `not_configured`), the answer must match `^w_[0-9A-Za-z_]{1,48}$` (else 503, nothing
stored), then it is stored once by compare-and-set (409 `version_conflict` after one attempt, a retry finds the same world).
The id never comes from the request. **Needs a change in `packages/people` (not `contracts/`):** `check_write` has no row
that adds `world_id` (create refuses it; the meeting edit row does not list it). The builder adds one row (absent to a
world id, owner only) with its own tests there; these tests pin only the HTTP behaviour.

## 7. Limits on the writes (SEC-09, #462, #464)

* **Body cap:** every people POST route refuses a body over `MAX_BODY_BYTES = 32768` with 413 `{"detail":
  "body_too_large"}` before reading the rest (a declared `Content-Length` over the cap is refused with no body read; a
  stream is cut after the cap plus one read-ahead of at most 64 KiB); a body of exactly the cap is read.
* **Idempotency-Key** (`^[A-Za-z0-9_-]{1,64}$`, else 422) on the four creates (meeting, person, work item, first person):
  same principal, key and body again returns the first answer byte for byte (status 201), creates nothing and (S5) emits
  nothing; racing retries create one record; the same key with another body is 422 `{"detail": "idempotency_key_reused",
  "code": "idempotency_key_reused"}`; another principal's identical key is independent (no oracle); a refused first attempt
  (403, 422) does not use the key up; no key, no deduplication. Mechanism is the builder's (for example an id derived from
  a keyed hash of principal and key, with create-if-absent, so it survives restarts and scale-out).
* **Rate cap:** `WRITES_PER_MINUTE = 60` per principal over every people POST route, every attempt that gets past sign-in
  counts (a 403, 404 or 422 too); reads do not. The 61st inside a minute is 429 `{"detail": "rate_limited", "code":
  "rate_limited"}` with `Retry-After` (whole seconds, 1 to 60), decided before the body is read; a minute after the first
  write the person may write again; another principal is unaffected. Time is `deps.get_clock`, and the counter belongs to
  the install's people stores (a fresh `PeopleStores` starts at zero), never to module state, so tests do not leak into one
  another.
* **No whole-org directory per write:** create meeting, create work item, both confirms and every S1/S2/S6 write read the
  actor's person record by id (at most two person records) and never call `persons.list`. Directory writes (create person,
  first person, memberships, roles) may list because uniqueness and membership need it.
* **no-store on every answer**, including 401, the SEC-15 gate's 403, a path or query validation 422, 413, 415 and 429.
* **Dev CORS:** `dev.install` allows the `Idempotency-Key` request header and exposes `Retry-After`.

## 8. New seams (`tilo_api.deps`; production defaults fail closed)

| Seam | Shape | Production default |
| --- | --- | --- |
| `get_event_writer()` | existing `EventWriter` | 503 `not_configured` (dev: `DevEventWriter`) |
| `get_desk_worlds()` | `.desk_world(org_id, user_id) -> world id`, lazy and idempotent | 503 `not_configured`; dev wires one |
| `get_meeting_worlds()` | `.make_meeting_world(*, org_id, owner, meeting_id) -> world id`, idempotent per meeting | 503 `not_configured` |
| artifact store, redactor | the T4 seams | `NotImplementedError` (503): needed by delete and minutes |

## 9. Guards and regressions (`test_PPL_11c_guards.py`, passing today)

The two event types are registered and fixtured; emails the contract already refuses stay 422; an item whose assigner is the
owner still gets `expired` from a discarded or deleted meeting (and from a missing one); the public route list is still the
pinned four.

## 10. Ambiguities resolved by default (also in the report)

1. POST for every change (no PATCH, no DELETE): dev CORS allows GET, POST, OPTIONS only.
2. A work-item action returns the full stored record (the owner reads it in full); the assigner's `confirm` keeps the status view.
3. A no-op edit is not pinned (no test).
4. Put back covers snoozed and asked items; a done item is put back with reopen. Not in the handoff list, in the 11a deferred list.
5. Delete drops only *proposed* work items, pins and calendar entries made from the meeting; released and confirmed records stay
   (BQ-PPL10-2). Active personal pins Tilo added from the owner's own meeting are not dropped; PE-16 or FR-MTG-10 may want them
   gone: user decision, one line in the test (`_with_derived`).
6. A deleted meeting is unreadable to its owner on `GET /v1/meetings/{id}`; the quotes route still answers `expired` (BQ-CCP3-2).
7. Attendee edit keeps a resolved `user` for an unchanged name (otherwise an edit would erase PE-15's resolution).
8. Minutes may be read before confirmation; the minutes read ends at `delete_minutes_after` with `>=`.
9. Email: ASCII dot-atom subset above, stored as typed, compared case-insensitively; the uniqueness answer (409 `email_taken`)
   is a small oracle to an org owner about their own org, accepted (the alternative is a silent success).
10. First person: allowed iff the org has no person and the principal has no record; the record id is the principal's id.
11. Rate cap 60 a minute per principal and body cap 32 KiB are defaults (no PRD number); both are constants the tests import
    nothing from, so a builder changes the number in `_ppl11c_lib.py` and the doc together.
12. A confirm's event goes to the assignee's Desk world (PE-12 reads "confirmed for P"); the other reading (the confirmer's
    world) is one line in `test_PPL_11c_s5_PE_12_a_confirm_is_written_in_the_assignees_desk_world_not_the_assigners`.
13. The Desk world id is `w_desk_<suffix of the user id>`; a user id whose suffix exceeds 43 characters has no Desk world
    (503): minted ids are 24 hex characters, so none today.
14. A failed event append undoes the write (503), not "event first": an event first would leave an event for a write that lost
    its compare-and-set, which is a lie in an append-only stream (EV-10).
15. Not done here, listed for follow-ups: the `owners()` sub-dependency note and the Firestore create-if-absent (#464), the
    `google` source owner and the plate `mine` check order (#462), `_MASK` linearity and quote word-boundary fallback (#456),
    PE-23/PE-24 amendment and `maxItems` on the history arrays (architect), invalid crossref cases for the stricter gone path.

## 11. Needs contract change, package change, user decision

* **Contract:** none for the routes. ADR-0009's `event.schema.json` change (`district_list` loses `minItems: 1`, EV-13 allows
  `[]` only when `district` is null) must merge before S5's dev-mode test can run; until then `vis: []` is asserted on the part
  and the schema check widens `vis`. The architect should also add `maxItems` to the history arrays, the stricter gone path to
  PE-23, and an invalid crossref case for it (follow-ups of #456).
* **`packages/people` (not `contracts/`):** `check_write` needs one row for adding `world_id` (S6); `INDEXES` may want
  `work_item`, `pinboard_item` and `calendar_entry` lookups by `source.ref` so a meeting delete does not scan the org (S2a).
* **Existing PPL-11a test changed:** `test_PPL_11a_PE_17_an_org_owner_creates_a_person_...` created the same person twice and
  expected two ids; with email uniqueness (S3) the second differs in its address. The property it pins (distinct minted ids)
  is unchanged.
* **User decisions:** (1) does deleting a meeting also delete the active personal pins and accepted calendar entries Tilo made
  from it (ambiguity 5)? (2) FR-MTG-01 attestation: still stamped automatically on create (#464, unchanged here).
