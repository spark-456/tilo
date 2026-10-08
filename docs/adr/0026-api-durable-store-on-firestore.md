# ADR-0026: tilo-api keeps worlds, tasks, policies and events in Firestore (addendum to ADR-0003)

- Status: Proposed (awaiting the supervisor's / user's OK), 2026-10-07, on the supervisor's defaults
  for PROD-WIRE (#522). It sets no switch, changes no contract and no `infra/`; that rollout is the user's.
- Deciders: supervisor (defaults), architect (proposal), user (approval, rollout)
- Requirement: PROD-WIRE; PRD 6.1, 6.2, 6.6, 15.1, 15.3; FR-HIL-07, FR-WLD-07, HR-1; ADR-0018 T4; BQ-PW-1
- Amends in part: ADR-0003 decision 1 and follows ADR-0023 (an ADR-0003 addendum line once accepted)

## Context
1. Deployed, `get_store` and `get_event_writer` answer 503 `not_configured`; only dev mode overrides them,
   in memory. `tasks._append` and `ScheduleStarter._create_world` extend `store.events` with a `seq` they
   computed, around the writer; `DevEventWriter` runs no stream rule (no `WorldState`).
2. The harness `WorldWriter` (lease, idempotent by id, EV-10 to EV-15) needs the layout when built
   (`scopes_for`, the EV-12/EV-13 ids) and has no `reopen()`; `FirestoreStore` is emulator and `demo-`
   only (ADR-0003). A run builds its layout after the plan compiles; the Director's planning events before
   it name `A_director`, a layout id.
3. A run is an in-process thread holding its plan, layout and `CardStore`; dispatch keeps its locks and
   queue on the `Store`; the api service runs `cpu_idle = true`, min 0, max 3. ADR-0023: a durable world
   store gets its own ADR and does not inherit the schedule switch.

## Decision
1. **One door, explicit config.** `open_api_store(env)` in tilo-api is the only code that builds a client:
   `TILO_API_STORE=firestore` plus a `TILO_FIRESTORE_PROJECT` matching the schedule store's `_PROJECT`
   regex opens `FirestoreApiStore` with the runtime identity's ADC. Its own guard: outside Cloud Run (no
   `K_SERVICE`) it opens only the emulator (`FIRESTORE_EMULATOR_HOST` and a `demo-` project), so a laptop
   with credentials never reaches tilo-dev. No `memory` value (memory is dev mode's). Read per request, a
   success cached per config; no config, another value or a bad project answers 503 `not_configured` on
   both seams, never cached, never a fallback to memory; `K_SERVICE` alone opens nothing. Import builds
   no client; no credential is in the repo. The harness `FirestoreStore` and its guard are untouched. Not
   chosen: reusing `TILO_SCHEDULES_STORE` (ADR-0023), loosening `FirestoreStore` (any caller could go live).
2. **Layout** under `orgs/{org}`, org = `deps.ORG_ID` until sign-in (ADR-0018 T4). Ids match their
   `common.schema.json` pattern (tasks: intake's `t_` + ULID) before a path is built.

   | Path | Holds |
   | --- | --- |
   | `worlds/{world}` | owner, districts, owner_channels, run_id, paused, prior_world_id, `layout` (null until the run builds it; PRD 15.1 World; a JSON string, see below), `created_at`, `rev` |
   | `tasks/{task}` | owner, world_id, run_id, draft, brief, questions, answers, edits, approaches, granted, scenario, gaps, next_seq (`Question`, `Gap` as fields; `draft`, `brief`, `edits` and `approaches` are JSON strings, see below), `created_at`, `rev`; never `lock` |
   | `policies/{policy}` | `{record, world_id, rev}`: the `policy.schema.json` record unchanged, and its `policy_worlds` world |
   | `worlds/{world}/events/{seq:08d}`, `.../views/{scope}/events/{seq:08d}`, `.../_head/state` | exactly the harness layout, written only by `WorldWriter` |
   | `worlds/{world}/_pending/queue` | `pending_events[world]`: the parts as built, in order, each a JSON string |

   *JSON strings.* Firestore refuses an array inside an array. The queued parts, the world's `layout` and the task's
   free-form `draft`, `brief`, `edits` and `approaches` can hold one (a brief edit is any JSON the brief schema
   accepts), so those are stored as JSON strings and decoded on read; every other field is a plain Firestore value
   (checked on the emulator, scenario policy records included).

   `pending_events` is durable because Pause all, Stop all and revoke apply their change before its event
   commits (FR-HIL-07): a queue lost at a restart would leave a paused world or lowered policy with no
   event queued or committed. `dispatch_state` (locks, attempts, futures), `runs`, `grant_locks` and
   `memory` (P7) stay in the process: they mean nothing to another. `firestore.rules` still denies every
   client; the world document holds server fields, so the client-rules ticket keeps it server-only.
3. **Write-through cache.** The process keeps one `Store`; routes read its plain dicts as today.
   - *Reads.* `get_store` loads the `world_id` and `task_id` in the request path on first access. Code that
     iterates an owner's worlds or policies (worlds list, cards feed, costs, earlier grants, dispatch's
     touched worlds, the run's policy reads) calls `store.load_owner(owner)` first, once per owner per
     process; the tick's starter loads what it reads. Loading a world reads its document, events by `seq`
     and queue, then drains the queue. A missing document is not cached (today's 404).
   - *Writes.* Under the record's lock a request commits its new values in one transaction that checks
     each record's `rev` and writes `rev + 1` (a new world or task by `create`, never overwritten), with
     its event parts, ids included, appended to the world's `_pending/queue`. Only then does it change the
     cached objects, drain the queue through `EventWriter.append` oldest first, and answer.
   - *Failure.* A failed or ambiguous commit leaves the cache as it was, evicts the touched entries (the
     next access reloads) and answers 503 `store_unavailable`; a `rev` mismatch answers 409 `stale`. A
     failed drain answers 503 (kill switches keep their 202 `pending`); the parts stay queued and the next
     load or dispatch resends them by id: no record without its events, no event twice. The cache is never
     ahead of Firestore except in the safe direction: Pause all, Stop all and revoke keep FR-HIL-07's order
     (applied here, no I/O under the mutate lock, then committed); if that commit fails the change stays
     applied here, so a run still stops (FR-WLD-07), and the answer is 503 "not saved".
   - Not chosen: dicts that read through on `get` (I/O under locks, no correct `.items()`), loading the
     whole org at cold start (grows with every world), write-behind (acknowledges what may be lost).
4. **One writer path for events.** Every event goes through `EventWriter.append`: intake's
   `world.requested` and file events, memory hits, the questions, approaches, `budget.granted`, scenario
   `policy.changed`, the scheduled start's, the run's and dispatch's. `tasks._append` and the extend in
   `_create_world` go; a repo test fails on any other write to `store.events`. The writer sets `v`, `seq`,
   `ts` (its clock), `world_id`, `run_id` and the null `trace`; `next_seq` is only the helpers' `seq=` hint.
   - *Adapter.* One harness `WorldWriter` per world over `FirestoreApiStore`'s events backend (the harness
     store protocol, `transaction.create` for event and view documents), org `deps.ORG_ID`, `run_id` and
     layout from the cached world record, never the part. `append` calls `emit(event_id=part["id"], ...)`:
     a same-content resend returns the committed event, other content raises `deps.EventRejected`,
     `WriterBusy` passes through by name. The committed event joins `store.events[world]` unless its id is
     there; that is the only cache write for events.
   - *Layout before the plan.* `{"semantic": {"levels": [], "islands": [], "gates": [], "agents": [{"id":
     "A_director", "rank": "director"}]}}`: one scope, `shared`, and EV-12 accepts `tasks.DIRECTOR`. It is
     the writer's input only, never stored, not a `layout.schema.json` document. `Run._prepare` commits the
     built layout to the world record before `world.started`, or the run fails ("the world could not be
     laid out"); the adapter reopens a writer whose world's `run_id` or `layout` changed. District views
     start at the layout (earlier events are in the stream and `shared`). Not chosen: an empty layout (EV-12
     refuses `A_director`), `WorldRecord.districts` (names only, empty in production), a view backfill.
   - *Lease and `reopen()`.* Writers stay open (30 s lease, renewed by each commit). A `WriterBusy` from
     `emit` reopens that world's writer once (an own lease lapsed while idle) and resends; a second one is
     raised. `reopen()` closes every open writer, releasing its lease, and forgets it; each reopens on its
     next append. SIGTERM closes them too, so a new revision does not wait out a lease.
5. **Runs stay in tilo-api on tilo-dev.** The api service gets `max_instance_count = 1` and
   `cpu_idle = false` (a per-service `cpu_idle` in the service module, default true). One instance: the
   run, its cards, dispatch's and the grant locks and the cache live in one process, and a second instance
   could neither see nor stop the first one's run (FR-WLD-07). CPU always on: a run works between
   requests. A run in flight at a redeploy or scale-in is lost, as today; with min 0 Cloud Run stops an
   instance about 15 minutes after its last request, losing a run that waits longer for a person. A world
   whose stream has `world.started` never gets a second run; a process that loads one with no terminal
   event, no run of its own and a free lease writes one `world.failed` (actor `system`, reason "the
   service restarted, so the work stopped", unit null) unless it is paused, so it does not look busy
   forever (HR-1). Way out, a later ticket: PRD 6.1's Cloud Tasks hand-off to a tilo-harness run route.
   *Cost:* instance billing (about US$0.000018 a vCPU-second, US$0.000002 a GiB-second, Tier 1 list; check
   asia-southeast1) is about US$0.07 an hour up for 1 vCPU and 512 MiB, US$50 to US$70 a month never scaled
   to zero. Min 0 (default, PRD 6.6) pays for hours up; min 1 keeps waiting runs at the full month. The
   user decides (BQ-PW-1).
6. **Indexes and IAM.** No composite index: gets by id, events by `seq`, worlds by `owner ==`, policies
   by `record.owner ==` (single-field, automatic). tilo-api already holds `roles/datastore.user`.
7. **Retention** (PRD 15.1): tasks, worlds and runs 90 days (a run has no document here), live events 30.
   Records carry `created_at`. Listed, not applied (infra, the user's): TTL policies on `worlds` and
   `tasks`. TTL deletes a document, not its subcollections, and events have no timestamp field, so the
   retention ticket chooses for events, views, `_head` and `_pending`: a field stripped on read, or
   FR-MEM-09's `purge_expired`. A world whose events expired is read-only to the writer.
8. **Tests.** As ADR-0023, a bomb client shows import and empty config refuse, and so do `memory`, other
   values, a bad project and a live project outside Cloud Run. The adapter and cache cases (writer `seq`,
   resend by id, conflict, reopen, layout switch, a failed commit leaving the cache unchanged, a cold
   `Store` equal to the warm one, queue drained) run over the harness `MemoryStore` by default and the
   emulator (`demo-` project) under `-m emulator`, with a parity test against `FirestoreStore`'s documents.

## What this does not change
- No contract (`WorldRecord`, `TaskRecord`, `Store` are tilo-api's types), no paid call, `LIVE=1`, dev
  mode's `DevEventWriter`, the schedule store and ADR-0023. Sign-in, artifact, redactor, archive, outbox,
  people, Desk and meeting seams stay as they are: a run starts on tilo-dev only when they land.

## Consequences
- Worlds, tasks, policies and events survive a redeploy; runs, cards and the outbox do not. Three
  Firestore adapters with three guards (harness emulator, schedules, api), on purpose.
- The deployed writer enforces EV-10 to EV-15 with a layout, which `DevEventWriter` never did; retiring
  it for the adapter over `MemoryStore` is a follow-up, as is serving the stored layout after a restart.
- In a rollover a kill switch may wait one lease (30 s) for a world the old instance holds, past
  FR-HIL-07's 5 s; accepted for tilo-dev.
