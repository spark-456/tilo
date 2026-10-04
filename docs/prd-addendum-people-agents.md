# PRD addendum: Meeting Agent and Personal Agents

Draft for the user's approval, 2026-10-04 (architect). Req: ADDENDUM-PEOPLE-AGENTS. Not part of the PRD (`docs/prd/` is read-only); on approval S0 folds the IDs into the ticket list. Contracts win over this text. Where the user has not decided, the smallest PRD-consistent default applies, marked "decision needed". Questions are `AQ-nn`; S0 maps them to `BQ-` ids. Nothing in `contracts/`, `config/` or code changes until the user approves.

## 1. Purpose and judging fit (PRD 4.1)

The user asked for (4 Oct): a **Meeting Agent (FR-MTG)** that joins a meeting or takes its transcript, understands it (summary, decisions, action items with owner and date, agenda coverage) and follows up; and a **Personal Agent (FR-PA)** per person that knows every task, meeting item and work item assigned to them ("what is on my plate", reminders, status, reply drafting) on web, WhatsApp and email.

Both pull PRD 23.3 (people as first-class actors) forward at personal scale. PRD 3.4 makes managing staff or calendars at company scale a non-goal and 23.5 forbids monitoring individuals, so this stays personal: test meetings, no cross-person dashboards, no talk-time or productivity scores (AQ-01).

Fit: Technical Merit (40%): reuses harness, Verifier and outbox; every extracted item cites transcript spans and code checks it; identity and dates are code, not model; the analyst has no tools (16.3). Problem Alignment, Innovation, UX (60%): meeting-to-follow-up is the Future of Work gap, measured by a new time-saved unit `meeting_minuted` against a hand-written baseline (EV-G2); meetings, mail and tasks meet in one plate, identical on every channel. Delete-the-model test (4.2): minutes and drafting break without the model; plate and reminders are code on purpose (PR-9), so the Personal Agent costs nothing idle. Candidate scenario SC-10 "Meeting to follow-up" becomes config-only afterwards (4.3).

## 2. Requirements

No clash for `FR-MTG`, `FR-PA`, `S-26`, `S-27` on `phase0-stack`, the meet-bot branches or AGW-07. `MF-` is avoided: `contracts/manifest.rules.md` owns MF-01 to MF-06.

### 2.1 Meeting Agent

| ID | Requirement | Acceptance test | Pri | Pillar | Depends on |
| --- | --- | --- | --- | --- | --- |
| FR-MTG-01 | A signed-in Owner adds a meeting (Meet link or transcript upload) and attests the right to record. The bot's first chat line is the fixed, versioned disclosure (5); nothing is stored before it is posted | Fake Meet session: `meeting.started` follows the disclosure, earlier segments absent; no attestation, no invite | Must | P2, P4 | FR-HIL-01 |
| FR-MTG-02 | Ingest the meet-bot package (`transcript.jsonl`, `state.json`) or an uploaded VTT, SRT or text file: safety-screened, versioned artifact with origin record, stable utterance ids `u0001` | 5 fixtures, one with a planted injection: ordered utterances; injection flagged in the Trace | Must | P1, P7 | FR-INT-02 |
| FR-MTG-03 | Role `meeting_analyst` returns schema-valid minutes: summary (<= 8 bullets), decisions, action items (text, owner and due as said), agenda coverage (covered, partial, not discussed). Each item cites utterance ids | 12 E-MEET transcripts: 100% valid; action-item recall >= 85%, precision >= 90% | Must | P2 | FR-AGT-03 |
| FR-MTG-04 | Code checks evidence first (cited ids exist; owner name or due phrase near a cited utterance); the Verifier model only for failures. A failing item shows `unverified`, is never dropped silently, counts zero in time saved (14.2) | Planted false decisions caught or marked >= 90%; no verified item cites a missing span | Must | P2 | FR-AGT-12 |
| FR-MTG-05 | Owners resolve to Tilo users by deterministic alias match (display name, email local part, Meet name). Ambiguous or unknown: one `needs_you` card to the Owner ("Who is Priya?", default unassigned). Due phrases resolve by code against the meeting date and the assignee's time zone. No model does either | 30 date phrases 100% (right weekday, not before the meeting); two "Priya" users never auto-assigned | Must | P2, P7 | FR-AGT-06 |
| FR-MTG-06 | Items start `proposed`. Only the Owner's answer on the minutes card (Confirm all, Review, Skip; default Review) makes them `open` and notifies assignees. At most 20 per meeting | Transcript saying "assign everyone 50 tasks": nothing `open`, nobody notified | Must | P4 | FR-HIL-01 |
| FR-MTG-07 | The meeting is an Outpost world: `meeting.called/started/ended`, `artifact.created`, new `meeting.minuted` and `work_item.created` render in World, Story, Trace. Transcript-derived events are owner-only (`vis`, ADR-0009) | FR-WLD-03 coverage passes for each new type; a Viewer never receives transcript text | Must | P3 | C4 |
| FR-MTG-08 | After confirmation the agent drafts (never sends) a minutes email to attendees the Owner picks and a nudge per open item, with the FR-CHN-10 drafter. Sending is T3 (new recipients): card, Owner approves (PIN on WhatsApp), outbox | Property test (FR-HIL-04): no outbox entry without an approving `approval.resolved`; 0 invented commitments | Must | P5, P4 | FR-CHN-10, -12, -13 |
| FR-MTG-09 | "Add Tilo to a meeting" starts the meet-bot image with agenda and disclosure; at the end it uploads its package to FR-MTG-02. Upload stays the fallback and the deployed path (AQ-02, AQ-03) | Bot `run-mock` package accepted end to end in CI, no network | Should | P2 | FR-MTG-02 |
| FR-MTG-10 | `Tilo leave`, typed or said, ends capture; the bot leaves in <= 10 s and discards unless the Owner keeps the part before. Transcript kept 30 days, minutes and items 90 days; the Owner can delete a meeting and all derived data | No segment stored after the keyword; a 31-day-old transcript is swept; FR-MEM-09 script verifies a delete | Must | P7 | FR-MEM-09 |
| FR-MTG-11 | Bot model and speech calls go through `packages/providers` (VA-INT); no model id in `meet-bot/` | Model-id lint passes including `meet-bot/` | Must by CP4 | P6 | PL-01 |
| FR-MTG-12 | Calendar read lists upcoming events with a Meet link and raises a join card (default skip) | 3 fake events: one card per Meet event | Could | P6 | FR-CON-14 |
| FR-MTG-13 | In-meeting answers cover only the agenda, minutes so far and the speaker's own items; else a one-line decline | 20 off-topic questions all declined | Should | P2 | FR-MTG-09 |

### 2.2 Personal Agent

| ID | Requirement | Acceptance test | Pri | Pillar | Depends on |
| --- | --- | --- | --- | --- | --- |
| FR-PA-01 | Work item: id, owner, title, due, status (proposed, open, done, dropped), source (meeting, mail, manual) with evidence ids, history. Made from confirmed minutes, from triaged mail the user marks "track", or by hand. Visible to its owner; the assigner sees status only | 3 sources each show link and history; user B gets 404 on user A's item | Must | P7, P4 | C1 |
| FR-PA-02 | "My plate": one deterministic order over open work items, open cards, status of the user's running tasks and mail needing a reply (FR-CHN-09): gates and blocked, overdue, due in 48 h, the rest | 10 seeded states equal the expected list; web, WhatsApp and email show the same ids | Must | P5 | FR-PA-01 |
| FR-PA-03 | Screens S-26 Meetings (minutes, evidence quotes, confirm) and S-27 My plate (done, snooze, "not mine"), on fixtures first | Playwright: confirm, done, snooze at desktop and mobile sizes; axe clean | Must | P3 | C1 to C4 |
| FR-PA-04 | WhatsApp commands, whole message, bound number only: `PLATE`, `DONE <n>`, `SNOOZE <n>`; numbers refer to the last list sent (24 h). No model classifies; all else is redirected as today | 12 command cases pass; the 30 E-CHN messages still 100% redirected; unbound number gets only the opt-in reply | Must | P5 | FR-CHN-03, -04, -06 |
| FR-PA-05 | Deterministic reminder sweeper (Cloud Scheduler, Cloud Tasks; the FR-CHN-08 pattern): due in 24 h gives a nudge, overdue one merged `needs_you` card a day; templates, no model. Window 09:00 to 18:00 local; <= 6 asks per person per hour (8.3); <= 1 proactive WhatsApp message a day (utility template), rest in the digest. One lazily created Desk world per user holds these events and cards | Fake clock: each rule fires once, never outside the window or above a cap; retries never duplicate | Must | P5, P4 | FR-PA-01, FR-HIL-02 |
| FR-PA-06 | Daily plate digest and reminder emails from Tilo's domain with signed single-use Done and Snooze links (FR-CHN-07). An emailed reply changes nothing (sender unauthenticated, 10.3) | Reused or expired link refused; emailed "done" ignored | Must | P5 | FR-CHN-07 |
| FR-PA-07 | A mail item on the plate offers "Draft reply", which runs FR-CHN-10, -11, -13 unchanged (tiers, undo, outbox). No new send path | SEC-03 static check passes; EV-15 p95 <= 15 s holds | Must | P5 | FR-CHN-10, -11, -13 |
| FR-PA-08 | `STATUS` gives one line per running task and per item changed since yesterday; weekly summary from a template | Equals world and item state on 5 fixtures | Should | P5 | FR-PA-02 |
| FR-PA-09 | "Follow up with Sam on X" drafts a message (T1). Sending is T2 in an existing thread to a known contact, otherwise T3; always a person in this release | No outbox entry without an approving event; no L2 or L3 | Should | P4, P5 | FR-MTG-08 |
| FR-PA-10 | Free-text updates ("done", "move it to Friday") parsed by role `personal` (cheapest profile). Own status and due apply at once with undo; a reassign is a request to the meeting Owner | 30 phrases >= 90%; a non-owner's phrase never changes state | Could | P5 | FR-PA-04 |
| FR-PA-11 | A plate is visible only to its person: no manager or team view of someone else's plate, no ranking, no activity score. Export and delete cover work items (16.5) | Another user, the meeting Owner included, gets 403 or 404; delete script finds empty stores | Must | P7, P4 | FR-MEM-09, FR-HIL-09 |

### 2.3 Named by the user, never specified: decision needed

Reserved IDs, not built. The meet-bot lane has unapproved in-meeting drafts for the same items (branch `chore/meet-bot-baseline`, `meet-bot/docs/specs/MF-01` to `MF-04`); not adopted here.

| ID | Item | Smallest PRD-consistent default | Pri |
| --- | --- | --- | --- |
| FR-PA-20 | Agenda | Per meeting, from calendar text, pasted text or `agenda.md`; coverage inside FR-MTG-03; no standing store | Must (in MTG-03) |
| FR-PA-21 | Team pinboard | A `pinned` flag, scope `team`, on a decision or work item, shown within that world's `vis` scope. No free-text pins | Could |
| FR-PA-22 | Personal pinboard | The same flag, scope `personal`; a filter on My plate, owner only | Could |
| FR-PA-23 | Responsibilities | One owner per work item; standing areas reuse Team Lead domains (`config/teams.yaml`, 8.3) | Could |
| FR-PA-24 | Effort tracker | Tilo's own effort only: credits and time-saved estimate per meeting and task (P8, 14.4). No human time or talk time (23.5) | Could |

## 3. MVP slice (demoable by 10 Oct; CP3 is 9 Oct)

**Demo path:** Owner uploads a 15-minute test transcript and attests; minutes appear with decisions, five action items and evidence quotes; "Who is Priya?" is answered on WhatsApp; Owner confirms; a second test user sends `PLATE`, `DONE 2` and gets the morning reminder (forced sweep); the Owner approves the follow-up email with PIN and it sends from a test Gmail through the outbox.

**MVP set:** FR-MTG-01 to -08 and -10; FR-PA-01 to -07 and -11; FR-MTG-09 is a labelled prototype in the video. **Cut first if behind** (PRD 5.5; never-cut list untouched): FR-PA-06, the send in FR-MTG-08 (keep drafts), WhatsApp proactive in FR-PA-05, FR-MTG-09. Contracts land on day 1, lanes then work in parallel on fixtures, integration on 9 Oct.

| Part | Reuses (not redone) | Paths | Lane (`docs/lanes.md`) |
| --- | --- | --- | --- |
| Contracts C1 to C6, ADR | Contract and registry tooling | `contracts/`, `config/`, `docs/adr/` | CL-TRUST (architect), first |
| Aliases, dates, work items, plate, reminder rules, routes | Policy engine, cards, `authz`, P7 preferences | new `packages/people/`; new `services/api/.../{meetings,work_items,plate}.py` | new lane CL-PEOPLE (new files only; CL-INT wires routes) |
| Minutes run: skill, prompt, fixed `meeting_followup` PlanGraph (no Director call), Verifier | ADK harness, envelopes, skills, FR-INT-09, -11, -02 | `skills/meeting-minutes/`, `prompts/`, `services/harness/` | CL-HARNESS |
| WhatsApp commands, sweeper, digest, Calendar adapter | Binding, keywords, FR-CHN-04, signed links, triage, drafter, send; Gmail (read live) | `services/channels/` (`plate.py`, `reminders.py`), `services/connectors/` | CL-REACH |
| S-26, S-27, event mapping | `meeting.*` events (BQ-24); S-09 stays the agent-called meeting (AGW-07), so S-26 does not block it | `apps/web/**` on fixtures | AG-WEB (Flash screens, Pro mapping) |
| Eval cases, checks, metering unit | Eval harness, `building.completed` | `evals/cases/**`, `evals/fixtures/**`, `evals/src/`, `packages/metering/` | AG-EVAL; CL-EVID |
| Disclosure, `Tilo leave`, package export, provider routing | `meet-bot/` image, `run-mock`, agenda, chat | `meet-bot/**` | MEET (user's Sonnet session) |

Minutes claims cite `<artifact_id>@<version>#u0042` as `cell` sources (FR-CON-10), so "Why is this here?" opens the utterance with no manifest change.

## 4. New events and contract changes: needs contract change (none made here)

- **C1 to C3** new `work_item.schema.json` (owner, due and `due_text`, status, source and evidence ids, `assigned_by`, history, snooze, pinned), `meeting.schema.json` (owner, agenda, attendees as said, consent `{attested_by, at, notice_version}`, artifact refs, `delete_after`), `minutes.schema.json` (summary, decisions, action items, agenda coverage, evidence ids, verification state).
- **C4** New events `meeting.minuted`, `work_item.created`, `work_item.changed` (registry row, data schema, fixture, renderer test each); additive optional `meeting_id` and `reason` on `meeting.started` and `.ended`. Owner-only `vis` needs ADR-0009 (Proposed, BQ-73) first. `unit_type` is an open slug, so `meeting_minuted` needs nothing.
- **C5** `person.schema.json`: the PRD 15.1 User entity has no contract; needs aliases, email, time zone, reminder preferences.
- **C6** Config: roles `meeting_analyst` and `personal` in `config/models.yaml` (open slugs); `config/personal.yaml` with a schema (window, caps, retention, disclosure version); `config/scenarios/meeting_followup.yaml`; `google_calendar` in `config/connectors.yaml` (Could); E-MEET and E-PA in `config/evals.yaml`.
- **No change:** card kinds and option ids (the reminder is a `needs_you` card with `done`, `snooze`, `not_mine`, all reversible), outbox, action types (follow-ups are `send_email` plus `new_recipients`, so T3), `channel.message_in`, manifest.
- One ADR (next number after 0013) for people, meetings and the no-monitoring line; a second if AQ-02 is accepted.

## 5. Consent, privacy and safety

1. **Who may record:** a signed-in Owner, in a meeting they host or attend, after a web attestation (not WhatsApp). Test meetings only, no confidential employer or client data (PRD 2.4).
2. **Disclosure and opt-out:** fixed, versioned text from config (AI notetaker, 30-day transcript, who sees it, `Tilo leave` stops it), posted in chat before capture and spoken when voice is on. Any participant can end it; default is discard (AQ-05).
3. **Retention and visibility:** no raw audio stored; transcript 30 days, minutes and items 90 days; deletion within 30 days of account deletion (16.5). Transcript and minutes are owner-only; an assignee sees their item, the meeting title and one evidence quote; sharing minutes is a T3 send.
4. **No monitoring (23.5):** no talk time, sentiment, ranking or activity score; no view of another person's plate.
5. **Follow-ups on someone's behalf:** a reminder to oneself is a notification. Any message to another person goes draft (T1), card, `approval.resolved`, outbox, with `authz` on `data.transfer`. A new email is T3 (BQ-171): L1 only, PIN on WhatsApp (SEC-06). A reply in an existing thread to a known contact is T2, still L1 here. No autonomous follow-up in this release.
6. **Injection:** transcript, Meet chat and calendar text are untrusted data. Model Armor screens first; the analyst has no tools and returns structured data to code; flagged content marks the minutes and makes any draft T3 with `safety_flag`. An item changes only by its owner or the meeting Owner, never by words in a transcript.
7. **WhatsApp (11.1):** `PLATE`, `DONE`, `SNOOZE` count as status of Tilo-tracked work; proactive messages use approved utility templates (test recipients in dev); no free-text chat. Google data stays under Limited Use (16.6).

## 6. Cost design and eval cases

- **Dev and CI:** fake providers, recorded answers, synthetic transcripts (names at example.com); no `LIVE=1`. The user records answers once; proposed cap 20 analysis calls.
- **Analysis:** transcript chunked by time, lowest-cost profile first, escalate on schema failure or Verifier rejection with the reason logged (EFF-02); evidence, dates and identity are code; one summary call; token caps on the new roles (EFF-03). Proposed target: a 60-minute transcript inside <= 100 credits (US$0.50), calibrated on the first recording, then set in config. Transcript-only mode sends no audio.
- **Personal Agent:** no always-on model; sweeper, plate and reminders are code and templates; a model runs only for a draft or a free-text update; one batched WhatsApp utility message a day per person (17.3).
- **Evals (deterministic first, 19.3):** **E-MEET** 12 scripted transcripts (recall, precision, evidence, dates, ambiguous names never auto-assigned, agenda, 0 invented commitments; summary rubric >= 4/5). **E-PA** 10 seeded states (plate order, reminders on a fake clock, cross-user denial, commands; 100%). **E-RED** +3 (injection in transcript, Meet chat, calendar text; 100% flagged, zero side effects). **E-CHN** +5 plate-adjacent off-topic messages (100% redirected). `config/evals.yaml` and the MT-10 count change with them; the full pass stays inside the 2,000-credit cap (BQ-43). Add "write minutes of a recorded 20-minute meeting by hand" to the EV-G2 timing study.

## 7. Open questions, each with the default we build on

| ID | Question | Recommended default |
| --- | --- | --- |
| AQ-01 | PRD 3.4 and 23.3 put people and calendar features at company scale on the roadmap | Approve personal scale only, with the 23.5 line written into the ADR |
| AQ-02 | `meet-bot` keeps a signed-in Chromium profile in a Docker volume; PRD 16.1 rule 3 and 3.4 forbid stored browser sessions | Strict reading: the deployed build uses upload; the live bot is a labelled prototype on the user's machine with its own bot account, behind an ADR and approval. Test guest join (no account, no stored session) first |
| AQ-03 | Where the live bot runs in the free week | Laptop Docker for the video; judges use upload; an on-demand VM is post-MVP (cost) |
| AQ-04 | Meet-bot speech uses a third-party vendor; hackathon rule 4.4 says Google models, built primarily on Google Cloud | Analysis is Gemini only; speech sits behind `SpeechProvider`; build a Google speech adapter if third-party speech is ruled out |
| AQ-05 | A participant objects; the meet-bot answers "any topic" when spoken to (PRD 3.4 bans a general chatbot) | Leave and discard, the Owner may keep the part before; answers limited to the meeting (FR-MTG-13) |
| AQ-06 | Retention; time zone and reminder window (BQ-44 fixed UTC for daily caps only) | Transcript 30 days, minutes and items 90 days; per-person zone, demo org Asia/Kolkata, UTC if unset; 09:00 to 18:00 |
| AQ-07 | Do `PLATE`, `DONE`, `SNOOZE` fit the task-scoped WhatsApp bot (11.1)? A persistent Desk world per user (a routine)? Items for others only after the Owner confirms? | Yes to all three; fixed commands only; scale to zero; 20 per meeting |
| AQ-08 | Pinboards, responsibilities, effort tracker | The 2.3 defaults, all Could |

## 8. The three decisions needed first

1. **Live bot: identity, place, speech vendor (AQ-02, AQ-03, AQ-04).** Is the stored-session exception and a third-party speech vendor acceptable, or do demo and judges rely on transcript upload, with the live bot shown on video?
2. **Scope (AQ-01, AQ-07).** Approve the personal-scale extension of PRD 3.4 and 23.3, the no-monitoring line, the WhatsApp commands and the Desk world.
3. **Pinboards, responsibilities, effort tracker (AQ-08).** Accept the 2.3 defaults (all Could) or say what you mean by each.
