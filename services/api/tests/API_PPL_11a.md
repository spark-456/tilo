# PPL-11a: the people API on tilo-api (what the acceptance tests pin)

> **Status (slices A, B and C).** All eight routes exist and every PPL-11a test file is green with no xfail:
> `SLICE_BC_PENDING` in `_ppl11a_lib.py` is empty (strict xfail would fail an unmarked pass), and `test_PPL_11a_writes.py`
> is restored from `origin/tests/PPL-11a-people-api`.

Source: `docs/prd-addendum-people-agents.md` (FR-MTG, FR-PA), `contracts/people.rules.md` PE-01 to PE-30, ADR-0020
(evidence quotes) and ADR-0021 (the plate), ADR-0015/16/17, `docs/open-questions.md` BQ-265 to BQ-273, BQ-CCP3-1 to
BQ-CCP3-3, BQ-PPL10-*, the PPL-10 follow-ups (PR #438), SEC-15 (`API_SEC_15.md`), SEC-16, EFF-01, PL-01, HR-1.
Built on `packages/people` (`tilo_people`: `decide`, `read`/`project`, `check_write`, `Directory`, the stores,
`resolve_due`). The names below are chosen by the test-writer; a builder may change one if it says so and edits the
tests in the same PR. Fakes only: in-memory people stores, an in-memory `ArtifactStore`, a fake redactor, fake plate
sources. No network, no paid call, no model id, no secret (the fake token is assembled at run time).

Tests: `services/api/tests/test_PPL_11a_*.py` (helpers `_ppl11a_lib.py`, fixture `people_rig` in `conftest.py`). The
crossref cases run through the real app and must match the reference oracle in
`tests/contracts/test_CC_PEOPLE_3_quotes_and_plate.py` (`expected_quotes`, `expected_join`, `_plate_problems`).

## 0. Size and suggested split (each slice is about 400 hand-written lines or less, green on its own)

| Slice | What | Test files |
| --- | --- | --- |
| **A** | `tilo_api.people` router, the seams below, `tilo-people` dependency, dev wiring, the two quote routes | `test_PPL_11a_quotes_crossref.py`, `test_PPL_11a_quotes_text_and_leaks.py`, `test_PPL_11a_gate_seams_and_dev.py` (the ids for B and C routes go green with those slices) |
| **B** | `GET /v1/plate`, six sources | `test_PPL_11a_plate_crossref.py`, `test_PPL_11a_plate_sources.py` |
| **C** | confirm (meeting minutes, work item), create meeting, create person, create work item | `test_PPL_11a_writes.py` |

Commits on the tests branch follow the slices (A, B, C), so a split can cherry-pick. Deferred to PPL-11c (not
pinned here): list/get/edit/done/snooze/reopen/not-mine/put-back of work items, meeting get/edit/delete (tombstone
call), the minutes read, writing `meeting.world_id` when the meeting's world is made, membership and org-role
changes, the first person of an org (sign-in), and the PE-12 events in Desk worlds. PPL-11b keeps pins, calendar, the
assistant and free/busy; its write routes must run the PE-13 pin-URL redactor and the secret redactor before
`check_write` (here the secret redactor and the PE-13 "no link" rule on meeting text are pinned).

## 1. Routes (all behind the SEC-15 gate; none is public)

| Route | Who | 200/201 body | Refusals |
| --- | --- | --- | --- |
| `GET /v1/meetings/{meeting_id}/quotes?ids=u0021,u0023` | the meeting owner | `{"quotes": [...]}` = `transcript.schema.json#/$defs/evidence_quotes`, one per id, in request order | 422 bad ids; 404 |
| `GET /v1/work-items/{work_item_id}/quote` | the item's owner | same shape, 0 or 1 quote; takes no argument (any query argument is ignored) | 404 |
| `GET /v1/plate` | the signed-in person | a valid `Plate` (`plate.schema.json`) | 404 no person record |
| `POST /v1/meetings/{meeting_id}/confirm` | the meeting owner | the stored meeting (200) | 404, 409 |
| `POST /v1/work-items/{work_item_id}/confirm` | the item's assigner | the `status` view `{id, title, status, due}` (200) | 404, 409 |
| `POST /v1/meetings` | any person of the org | the stored meeting (201) | 403, 422 |
| `POST /v1/people` | an org owner | the membership view `{id, display_name, org_role, memberships}` (201) | 403, 422 |
| `POST /v1/work-items` | any person of the org | the stored work item (201) | 403, 422 |

Statuses: 401 signed out (the existing default); 403 + `code` from the SEC-15 gate; **404 `{"detail": ...}` for a
refused read or confirm of anything, one body whatever the cause** (unknown, malformed or other org's id, not yours,
wrong state, a person with no record, a swept or deleted meeting for a non-owner); 403 for a refused create (no record
is revealed); 415 for a POST whose body is not `application/json`; **422 for a bad shape: ids list, an extra body
field, a schema-invalid text** (shape and schema come before authorisation, so they are no oracle); 409 `{"detail", "code":
"version_conflict"}` for a lost compare-and-set (one attempt, no retry) and 409 `{"detail", "code": "write_refused",
"problems": [<check_write codes>]}` for a state the MAY row refuses; 503 `{"detail": "not_configured"}` for an unwired
seam, and 503 for a source or store that cannot be read (never a 500, never a partial answer). Path ids that do not
match their pattern are the same 404 as unknown ones.

Bodies are closed: any field not named below is a 422. **No id, org, owner, stamp, status, source, evidence, history,
world or `due` ever comes from a request body.**

## 2. Quotes (ADR-0020, PE-22 to PE-25; BQ-265 to BQ-268, BQ-CCP3-2)

* The meeting owner gets one quote per id (1 to 20 ids matching `^u[0-9]{4,6}$`, comma separated; a malformed list is 422
  for everyone, before any lookup). Anyone else, a meeting that never existed, another org's meeting: the one 404.
* An item's owner (Tilo-made, `open|done|dropped`, `confirmed_by` by its assigner, minutes confirmed by the meeting
  owner) gets at most one quote: the lowest id both the item and its minutes action item cite and the pinned version
  holds, else the lowest shared id; no shared id: `{"quotes": []}`; no meeting title anywhere.
* Gone: `now >= meeting.delete_transcript_after` (compared with `>=`, the server clock) or the transcript version not
  found in the meeting's own scope (org, `world_id`, owner, all from the stored meeting) gives every id `expired`
  with `transcript` null, only to a reader PE-23 admits: the owner on the owner route (also when the meeting is
  discarded or deleted, from the record or its tombstone), the item's owner on the item route (also when the meeting
  is missing, discarded or deleted), naming the lowest id the item itself cites on every gone path. A meeting
  without `world_id` yields no quote (404).
* Held back (non-owner): `withheld` unless the transcript version is `screening: clean` and the minutes are not `flagged`.
  **Stricter than the oracle (ambiguity 4):** in that case the id is the lowest shared id and the transcript's content
  is never consulted for it.
* Text for every viewer: remove Unicode Cc, Cf, Zl, Zp from text and speaker, pass the shared secret redactor
  (`deps.get_redactor`, owner included), then for a non-owner mask addresses, phone numbers and links as `[removed]`,
  then cut at 240 characters on a word boundary (`truncated`). A non-owner's speaker is the directory display name of the
  attendee the label resolved to, only for themselves or a teammate, else null.
* Nothing is stored, logged, cached or put in an event; a read changes no record and no artifact. A corrupt artifact is 503.

## 3. The plate (ADR-0021, PE-26 to PE-30; BQ-269 to BQ-272, BQ-CCP3-1, BQ-CCP3-3)

`GET /v1/plate` builds the signed-in person's plate (`user` = principal, `as_of` = the clock, `today` = the date in the
person's zone) from: their own work items, pins, mentions and meetings (stores), cards, runs and mail (plate sources),
and their own calendar entries starting today in their zone. Nothing names another person (query, header and body are
ignored). `rows` and `parked` obey PE-27 exactly as `expected_join` says; groups, order, caps (200 rows, 100 parked),
`truncated` (only for readable overflow) and `fingerprint` are code (`_plate_problems` must be empty). Row fields:
work item: title, `due`, `at` = `created_at`, `from` = an assigner other than the owner, `evidence`, `actions` (`not_mine`
only when someone else assigned it, `put_back` only in `parked`); pin: `at` = `updated_at`, `from` = setter other than
the person, reason `pin_owner` (own, or personal) or `pin_tagged`; card: reason `gate|consent` by kind, `needs_you` is
`blocked` when `rung` is `blocked` else `question`, `meeting` is `meeting_card`; `at` = `created_at`; run: `world` ref,
reason `run` or `blocked`, title the goal cut to 140, `due` = deadline, `at` = start; mail: ref = the triage message id,
reason `mail_reply`, group `rest`, title/due/from null, actions include `draft_reply`; calendar: `calendar` / `soon`,
`at` = start. Titles are cleaned like a quote line. A source that fails is 503, never a partial plate (ambiguity 6). A
record with a very long `history` is unreadable (ambiguity 7). The plate touches neither the artifact store nor the redactor.

## 4. Seams (`tilo_api.deps`; production defaults fail closed)

| Seam | Shape | Production default |
| --- | --- | --- |
| `ORG_ID` | read at call time (`deps.ORG_ID`), never a request's; the API loads this one org only | `"org_tilo"` (T4) |
| `get_people_stores()` | `tilo_people.stores.PeopleStores` | 503 `not_configured` |
| `get_artifact_store()`, `get_redactor()` | the T4 seams, reused (transcripts and minutes are read through the store with the meeting's own `Scope`) | raise `NotImplementedError` today; the routes answer 503 `not_configured` |
| `get_clock()` | `Callable[[], str]`, a `common#timestamp`; read once per request | the real clock (`events.now`) |
| `get_plate_sources()` | `.cards(user_id)`, `.runs(user_id)`, `.mail(user_id)`, each an iterable of dicts; a source may return everything it holds, the API filters again | 503 `not_configured` |
| `get_source_owners()` | `.owner_of(kind, ref) -> user id or None`, kind `mail` or `request` | 503 `not_configured` |
| `NOTICE_VERSION` | semver string stamped as `attestation.notice_version`, read at call time | `"1.0.0"` |

Card fact: `{"data": <card.schema doc>, "world_owner": user, "approver": user | None, "answered": bool}`. Run fact:
`{"world_id", "world_owner", "state": "running"|"blocked"|..., "goal", "deadline": date | None, "started_at": ts}`; only
`running` and `blocked` of a world the person owns join. Mail fact: `{"message_id", "account_owner", "received_at", "flagged",
"answered", "dismissed"}`. The routes depend on a seam only when they use it (the plate never needs the artifact store or the redactor).

`tilo_api.people` exposes `router`, mounted in `tilo_api.app`. Add `tilo-people` to `services/api/pyproject.toml`
(workspace source). Dev mode (`dev.install`) wires one in-memory `PeopleStores` per install with the dev owner as an
org owner of `deps.ORG_ID`, empty plate sources and source owners, each re-checking `refuse_if_unsafe()` per call
(deployed or `LIVE=1` raises `DevModeRefused`). The people modules make no model call, build no router, read neither
`replay_only` nor `LIVE` nor `TILO_JUDGE_LIVE` nor the flag store, and import no network client (a static test scans
`tilo_api/people*.py`); a router spy fails the tests if any is built.

## 5. Writes (PE-03, PE-07, PE-08, PE-17, PE-18, PE-19; BQ-PPL10-*)

Every write: schema first (422), `decide` (404 or 403), build `after` with stamps `{actor, server now}`, redact every
text field, `check_write`, `replace(expected_version)`. The secret redactor runs **before** the schema check (a 100-character title
plus a 54-character fake token passes as 110 characters; a link in a meeting title, agenda title or attendee name is 422, PE-13).

* Work-item confirm: only the assigner (`assigned_by.by`) of a `proposed` item; `confirmed_by` = {actor, now}, status
  `open`, one `confirmed` history entry, `updated_at` = now; response is the `status` view. A second confirm changes nothing.
* Meeting confirm: only the owner, on a `minuted` meeting with no confirmation; `minutes_confirmed_by` = {actor, now}; a confirmed
  meeting is 409 `problems` containing `transition`. Confirming opens the assignee's quote (PE-23).
* Create meeting: body `{title, source: bot|upload, series?, scheduled?, agenda?, attendees?: [{name}]}`; the server mints `mt_...`,
  sets owner, `org_id`, `attestation` {actor, now, `NOTICE_VERSION`}, status `scheduled`, no `world_id`, `transcript`, `minutes` or
  confirmation; attendees are stored with `user: null` (`attendees[].user` is never identity and never taken from a request).
* Create person: org owner only; body `{display_name, aliases, email, time_zone, preferred_channel}`; the server mints `u_...`
  (never from input, distinct per call), `org_id` = `deps.ORG_ID`, `org_role: member`, no memberships, `created_by` {actor, now}.
* Create work item: body `{title, due_text?, source: {kind: manual|mail|request, ref}}`; owner = caller, `created_by` {person, caller, now}, no
  assigner, `due` computed by `resolve_due(due_text, meeting_at=now, time_zone=<caller's>)`. A `mail` or `request` source needs
  `owner_of(kind, ref) == caller` (PE-08); someone else's ref and a missing ref give the same 422 body `{"detail", "code": "source_not_found"}`.

## 6. Ambiguities resolved by default (also in the report)

1. `ids` is one comma-separated query argument; a bad list is 422 (the oracle says "no quotes", i.e. a 404).
2. A card row's title: the cleaned `what_happened` or null (ADR-0021 says "card header", which is `{building, agent}`, not text).
3. A transcript version stored in another world looks to the store like a swept one: the API answers 404 or all-`expired` for an admitted
   reader, never text (`pe19_version_from_another_world` is the one oracle case relaxed to that).
4. Held-back transcripts: the id is chosen from the two citations alone (stricter than `_assignee_ids`). Needs a one-line PE-23/PE-24
   amendment and an oracle update (no fixture changes: every current case agrees).
5. Mail facts carry `received_at`, `answered`, `dismissed`; the triage store keeps only `triaged_at` today, so its adapter must add them.
6. A failing plate source is a 503, not a partial plate (HR-1).
7. `work_item.history` has no `maxItems`: the API treats a record with more than a small cap as unreadable (404, off the plate), never runs
   `decide` over it; tests use 5,000 entries (refused, under 2 s) and ordinary ones (fine). Recommended: the architect adds `maxItems` to the history arrays.
8. A principal with no person record in `deps.ORG_ID`: 404 on reads and confirms, 403 on creates.
9. No event is emitted in this ticket (the Desk worlds PE-12 names do not exist yet); the PE-12 events are PPL-11c.
10. A person's typed text is not run through the safety provider (it is their own data); flagged applies to machine-read text.
11. The due anchor of a person-made item is "now" in the caller's zone; an unparseable zone is `bad_time_zone` (due null).
12. A calendar entry is "today" by its `start` in the person's zone; a parked item that is both snoozed and reassign-asked is `asked`.
13. The item route's `expired` answer rests on the Tilo-made stamp, which only `tilo-api` writes through `check_write`; a forged
    person-made item naming someone's meeting gets the same 404 whether that meeting exists.

Needs contract change: none. Recommended for the architect: `maxItems` on `work_item.history` and `pinboard_item.history` (7), the held-back
rule in PE-23/PE-24 (4).
