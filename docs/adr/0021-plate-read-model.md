# ADR-0021: The plate read model

- Status: Accepted by the user, 2026-10-05 ("accept all of #381": Option A with the new plate contract and `mail` added to `record_ref.kind`). Proposed earlier the same day by the architect (BQ-PPL40a-2). It adds a new contract, widens one
  shared enum and adds five rules to the people contracts, so it needs the user's approval before
  ticket CC-PEOPLE-3 makes it. This PR is docs only: nothing in `contracts/`, `config/` or code
  changes here. Lands with ADR-0020 (evidence quotes).
- Deciders: user (approval), architect (proposal)
- Requirement: FR-PA-02, FR-PA-03, FR-PA-06, FR-PA-13, FR-PA-16, FR-PA-17, FR-PA-19
  (`docs/prd-addendum-people-agents.md`; `docs/prd-supplement-2026-10-05.md` 3.1); FR-CHN-09;
  PE-01 to PE-04, PE-10, PE-11, PE-20, PE-21; ADR-0006, ADR-0016 decision 1; HR-1 (PRD 9.4)

## Context
1. FR-PA-02 (Must): one deterministic order over open work items, open cards, the status of the
   person's running tasks, mail needing a reply, pins the person owns or is tagged on, and today's
   calendar: gates and blocked, overdue, due in 48 h, the rest. Test: 10 seeded states equal the
   expected list, and the web, the email digest and the panel show the same ids.
2. ADR-0016 decision 1: records are the source of truth, events the audit trail; plates are read
   from records through `tilo-api`, never from another person's event stream.
3. PPL-40a (PR #376) builds S-27 on work items only. `apps/web/src/people/plate.ts` computes the
   groups in the client (overdue, due within two days of a fixed preview day, the rest), and
   lanes for snoozed, reassign-asked and done items, with Done, Snooze, Not mine and Put back
   (`reducePlate`, which writes `work_item.history` entries). `canReject` reads `assigned_by`.
   Cards, runs, mail, pins and the calendar have no plate row and no contract.
4. Mail triage (`services/channels/src/tilo_channels/triage.py`) stores a category per message id
   and, on purpose, no subject, body or display name. `common.record_ref.kind` has no `mail`, so
   the panel (FR-PA-13) cannot cite a mail row as an answer's source today.

## Decision (Option A)
1. **One builder, never stored.** `tilo-api` computes the plate per request for the signed-in
   principal only: no route, query or argument names another person (no manager view, D-3). It is
   never stored and never an event. S-27, the digest (FR-PA-06) and the panel (FR-PA-13) all read
   this builder's `rows`, so "same ids" holds by construction.
2. **What joins `rows`** (BQ-269, BQ-270, BQ-272):
   - work items the person owns, `open`, not snoozed at `as_of`, last change not
     `reassign_requested` (never `proposed`, PE-03);
   - unanswered, unexpired cards the person may answer under PRD 10.1 and ADR-0006, in worlds they
     own or gates naming them as Approver (from the card store and events, as the needs-you
     reducer does);
   - runs of worlds the person owns that are running or blocked;
   - mail the triage store holds as `needs_reply` for the person's own connected account and not
     yet answered or dismissed;
   - active team pins whose `owner` is the person or that carry an active mention of them, while
     PE-02 lets them read the pin, and their own active personal pins that have a `due`;
   - their own calendar entries (accepted or proposed) that start on `today`.
   Nothing comes from a world where the person is only a Viewer or a Team Lead.
3. **`parked`** holds the person's own work items that are snoozed, asked to be reassigned, or done
   in the last 24 hours, for S-27's lower lanes and Put back. The digest and the panel ignore it
   (BQ-271).
4. **Groups and order are code (PR-9).** `attention`: gate and consent cards, blocked cards,
   blocked runs. `overdue`: `due` before `today`. `soon`: `due` from `today` to `today` + 2 days,
   today's calendar entries, other open cards. `rest`: everything else (running runs, mail, items
   due later or with no date). `today` is the date in the person's `time_zone` at `as_of` (server
   clock). Within a group: `due` ascending (null last), then `at` ascending (null last), then
   `ref.kind`, then `ref.id`.
5. **What a row carries.** A reference, never content beyond a title: the record's own title (work
   item, pin or calendar entry title, card header, the run brief's goal cut to 140 characters) or
   null for mail (triage stores no subject; the row reads "Mail that needs your reply"). `due` is
   the item's, pin's or brief's date; `at` is the card's creation, the run's start, the work item's
   creation, the mail's receipt, the pin's last change or the calendar entry's start. `from` is
   a user id (an assigner other than the owner, a pin's setter), shown by name only under PE-20.
   No quote (ADR-0020), body, address, link or transcript line. `flagged` copies the record's
   (PE-21). `actions` is a hint computed from PE-03, PE-07 and PE-10 (`not_mine` only on an item
   someone else assigned); `tilo-api` checks every action again at the write.
6. **Honest changes (HR-1).** A row moves or leaves only after its write commits and its event
   (`work_item.changed`, `approval.resolved`, ...) is recorded; no optimistic move. `truncated` says
   when rows beyond the cap exist. `fingerprint` (SHA-256 of the canonical `rows`) is the panel's
   cache key (FR-PA-19).

## Options
| Option | What | Verdict |
| --- | --- | --- |
| **A (recommended)** | Read model computed per request by one `tilo-api` builder; `plate.schema.json`; `mail` in `record_ref`; five rules | ~0.5 day contracts (CC-PEOPLE-3), ~1.5 days builder (PPL-11a, six sources), ~0.5 day web (PPL-41); digest and panel reuse it |
| B | A materialised plate document per person, updated from events | Rejected: new state to keep consistent and erase (PE-16), stale between writes, and a second copy of private rows |
| C | The client merges the sources itself, as the preview does | Rejected: three implementations of the order (web, digest, panel), and the client would receive whole records it does not need |
| D | `plate.*` events carrying snapshots | Rejected: ADR-0016 decision 1 and PE-12 (events carry ids only, in the actor's world) |

## Contract changes (ticket CC-PEOPLE-3, T1; all additive)
- **New `contracts/plate.schema.json` 1.0.0, title `Plate`:** `{v: "1.0", user, as_of, today
  (calendar_date), rows (at most 200), parked (at most 100), truncated, fingerprint
  (^[0-9a-f]{64}$)}`. `$defs/plate_row`: `{ref, reason, group, title (1..140, no control
  characters) | null, due (calendar_date) | null, at (timestamp) | null, from (user_id) | null,
  flagged, evidence (a meeting-sourced work item with a cited utterance), actions}`.
  `ref` is a `record_ref` narrowed inline to `work_item`, `card`, `world`, `mail`, `pinboard_item`,
  `calendar_entry`. `$defs/reason`: `gate`, `consent`, `blocked`, `question`, `meeting_card`,
  `run`, `work_item`, `mail_reply`, `pin_owner`, `pin_tagged`, `calendar`. `$defs/group`:
  `attention`, `overdue`, `soon`, `rest`, `snoozed`, `asked`, `done` (the last three in `parked`
  only, work items only). `$defs/action`: `open`, `done`, `snooze`, `not_mine`, `put_back`,
  `draft_reply` (unique, at most 6).
- **`common.schema.json` 1.2.0 to 1.3.0:** `record_ref.kind` gains `mail` (the triage message id,
  which fits the existing id pattern). Widening the enum keeps every document valid; TypeScript
  switches over `kind` need the new case.
- **`contracts/people.rules.md`:** PE-26 (decision 1), PE-27 (decisions 2 and 3), PE-28
  (decision 4), PE-29 (decision 5), PE-30 (decision 6). Crossref cases: the person's own plate;
  refused: a proposed item, a teammate's personal pin, a pin after the person left the team, a
  card in a world where they are only a Viewer, another person's plate.
- **Fixtures:** `fixtures/plate/{valid,invalid}` (invalid: a parked group in `rows`, a parked row
  that is not a work item, a `ref` to a meeting (PE-05), a repeated action, a title with a
  newline, an unknown reason); E-PA's 10 seeded states become `Plate` documents.
- **No new event.** Plate actions write the existing `work_item.changed` (`done`, `snoozed`,
  `reassign_requested`, `reopened`) in the person's Desk world (PE-12); the registry is unchanged.

## Builders (after T1)
- PPL-11a: `tilo_api.plate.build(principal, now)`, `GET /v1/plate`, and the item actions; the
  crossref files in its tests. PPL-30 (digest) and PPL-40c (panel) call the same builder.
- PPL-41: S-27 reads `Plate`; `plate.ts` keeps only display helpers; the fixture becomes a `Plate`.
- PPL-50, PPL-51: E-PA plate order on 10 states (ids equal across web, digest and panel); E-PRIV.

## Security notes
- Owner-only: the principal is the only input that picks a plate. A Viewer, Approver or Team Lead
  never sees another person's rows; a teammate's display name appears only under PE-20.
- No cross-world leak: card and run rows come only from worlds the person owns or gates that name
  them; mail rows only from their own connected account.
- Untrusted titles (from minutes, mail-made items, pins) render as plain text. In the panel's
  model fallback, rows are delimited data and only a validated `ui_action` can come back (PE-10).
- Flagged records stay flagged on the row; any follow-up from one is T3 (PE-21).

## Consequences
- S-27 goes live with all six sources and the order FR-PA-02 tests.
- Mail rows stay terse until triage keeps a screened subject (a separate decision).

## Open questions (`docs/open-questions.md`)
- BQ-269: mail rows. Default: no subject or sender; `mail` joins `record_ref`.
- BQ-270: which cards and runs, and their groups. Default: decisions 2 and 4.
- BQ-271: the parked lanes. Default: snoozed until `snoozed_until`, asked until reassigned, done
  for 24 hours; not in the digest or panel.
- BQ-272: time and caps. Default: `today` in the person's time zone; "due in 48 h" means a due
  date up to `today` + 2 days (the preview's rule); personal pins only with a `due`; caps 200 and
  100.

## Implementation (CC-PEOPLE-3, 2026-10-06)
- `plate.schema.json` 1.0.0, `common.schema.json` 1.3.0 (`mail` in `record_ref.kind`), rules PE-26 to
  PE-30. The schema also ties `ref.kind` to the work item and mail reasons, `attention` to gate,
  consent and blocked rows, and `evidence` and the per-kind `actions` to their kinds.
- `evidence` is a boolean (BQ-CCP3-1). The crossref cases are `fixtures/plate/crossref/` for work
  items, pins and cards; runs, mail and calendar rows are left to the builder's tests (PPL-11a).
  E-PA's 10 seeded states stay with PPL-50.
