# ADR-0023: The schedule store opens a live Firestore only by explicit config (addendum to ADR-0003)

- Status: Proposed by the architect, 2026-10-06, on the supervisor's option B decision for
  FR-AGT-14b, which set the conditions: a live Firestore path needs this ADR, an explicit switch,
  and a test that the default refuses. It takes effect when the 14b PR merges. Nothing here sets
  the switch or applies infrastructure: the user does that at rollout (PR 2). This ADR changes no
  contract.
- Deciders: supervisor (option B and its conditions), architect (proposal)
- Requirement: FR-AGT-14 (PRD 8.6); ADR-0003 decision 1; BQ-AGT14-1, BQ-AGT14-2, BQ-AGT14-3
- Amends in part: ADR-0003 (one-line note there)

## Context
1. ADR-0003 decision 1 made the build local-first. `tilo_harness.store.FirestoreStore` is the one
   Firestore adapter: it refuses anything but the Firestore emulator (`FIRESTORE_EMULATOR_HOST`)
   and a `demo-` project id, with no cloud credentials. That is right for world events in dev and CI.
2. The Google Cloud project has been live since 4 October (billing on, infrastructure applied), but
   no durable store exists for anything the harness or `tilo-api` keeps. `tilo-api` holds tasks,
   worlds and runs in memory, so a redeploy loses them.
3. FR-AGT-14 needs the opposite for one record: a weekly schedule must still be there next week,
   after any number of redeploys. The schedule record (BQ-AGT14-3) is small, owner-scoped and holds
   no secret.
4. Loosening the `FirestoreStore` guard would let every harness caller reach a live project by
   accident. The guard is a hard rule of the local-first build, not an inconvenience.

## Decision
1. **A separate class.** `tilo_harness.schedule_store.FirestoreScheduleStore` is its own class with
   its own guard. `FirestoreStore` and its emulator/`demo-` guard are not touched, and a test still
   proves they refuse.
2. **One door, explicit config.** `open_schedule_store(env)` is the only code that builds a store.
   `TILO_SCHEDULES_STORE=firestore` plus `TILO_FIRESTORE_PROJECT` (a GCP project id) opens a live
   Firestore client. `TILO_SCHEDULES_STORE=memory` returns the in-memory store. No config, an unknown
   value, or `firestore` without a project raises `ScheduleStoreNotConfigured` before any client
   exists. Importing the module builds no client. The default configuration never opens a live path.
3. **`tilo-api` reads the switch on each request.** Unset: the in-memory store in dev mode
   (`TILO_API_DEV=1`, never when deployed or live), otherwise 503 `not_configured`. A refusal is
   never cached and never falls back to memory when deployed, so a missing variable is loud, not a
   silent loss of schedules.
4. **Tests prove the default.** `tests/repo/test_FR_AGT_14b_schedule_store_guard.py` replaces the
   Firestore client with a bomb and checks that import and the empty config both refuse. The same
   conformance cases run against the in-memory store in the default run and against the Firestore
   emulator under `-m emulator`, with a `demo-` project id.
5. **The id never reaches a path.** Schedule ids match `^sched_[0-9A-Za-z_]{1,64}$` before any
   document path is built; the record lives at `orgs/{org}/schedules/{schedule_id}`.

## What this does not change
- No cloud credentials in dev or CI: the repository holds none, and a deployed service uses its
  own runtime identity. Tests use the emulator or memory.
- No paid call, and `LIVE=1` is untouched (the user's alone). The store is not a model call.
- `tilo-api` still holds the run in memory. The schedule record is durable; a run in flight at a
  redeploy is lost, as every run is today. World events stay in the in-memory `Store`.
- `infra/` is not touched here: granting the runtime identity Firestore access, setting the two
  variables and retargeting the Scheduler job are the user's rollout (PR 2, security-flagged).

## Consequences
- A schedule survives a redeploy once the user sets the switch and applies PR 2; until then a
  deployed `tilo-api` answers the schedule routes with 503.
- There are two Firestore adapters with two guards, on purpose. A future durable world store gets
  its own ADR; it does not inherit this switch.
- The tick route, the starter and the record's fields are BQ-AGT14-3 (`docs/open-questions.md`).
