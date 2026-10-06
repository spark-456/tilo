---
name: schedule-tick-fr-agt-14
description: FR-AGT-14 scheduled runs: r1 FAIL (6c49214), r2 PASS flagged (a7ba44d); 14b r1 FAIL licence only (27dd27e); 14c infra retarget to api r1 PASS flagged (952324e2); open code list gates the user's env vars
metadata:
  type: project
---

**14c infra retarget r1 (2026-10-06, 952324e2, branch feat/FR-AGT-14c-infra-retarget) PASS flagged.** Tick job -> public tilo-api, SA holds NO IAM
(precedent: channels allUsers, ACCESS.md "no /internal route may rely on ingress or IAM"), composite index (COLLECTION scope is right: store uses a plain
`orgs/org_tilo/schedules` collection query, not collection_group), deny-all firestore.rules. terraform test 55 pass, tests/repo 286 pass, 3 adds vs origin/main.
Facts verified: Scheduler stamps `audience` verbatim (route compares byte-exact, user must copy `terraform output schedule_tick` audience; Cloud Run has two
URL forms, not verifiable offline); egress needs nothing new (subnet private_ip_google_access, system default route kept, no firewall/NAT/DNS zone), but
a cert-fetch failure is a SILENT 401 (schedules.py `except Exception` logs nothing); certs fetched per request, no cache, `requests` default timeout 120 s
on the 40-thread sync pool; tick still resolves `store`+`run_seams` before the token (3 anonymous 401 = 3 seam builds, probe_tick.py); deployed api
`deps.get_store` raises 503 so setting the 4 env vars alone does NOT make the tick work (docs say it does); emulator writes its own firebase.json
(`"firestore": {}`) so repo rules never touch tests; deploy is `--only hosting`, so firestore.rules is deployed by nobody (needs
`firebase deploy --only firestore:rules`, firebaserules.admin is user-side). Builder edited worktree files uncommitted during review (comments only).
Gate for the user before setting TILO_SCHEDULE_TICK_*/TILO_SCHEDULES_STORE: deploy rules, short cert timeout+cache+log, seams after auth.

**14b r1 (2026-10-06, 27dd27e, branch feat/FR-AGT-14b-schedule-store-routes) FAIL, one blocker, security-flagged** (new public route
`POST /internal/schedules/tick` on tilo-api in PUBLIC_ROUTES + SEC-15 pin; ADR-0023 live Firestore door amends ADR-0003).
Blocker: `tilo_api/schedules.py:126-127` is the first production import of `google.auth` / `requests` in the repo; neither is declared in
services/api/pyproject.toml nor in docs/licences.md (both Apache-2.0, already in uv.lock transitively). Fix = declare + two rows.
Tests: api FR_AGT_14|SEC_15 359 pass, harness FR_AGT_14 210 pass, tests/repo 283 pass; emulator suite could NOT start here (TimeoutError in
running_emulator, env), so FirestoreScheduleStore verified by reading only.

Closed from r1/r2: iss (tick_caller_ok on both routes, exact set, verified claims only); budget_cap (Schedule + schedule_from_doc); head-of-line
(record_failure + backoff + MAX_FAILURES 8 + due() skips backoff); misaligned next_due (schedule_from_doc quarantines; _latest_slot 0.2 ms from year 1);
owner from principal, extra=forbid, 404 same for unknown/other on every verb and create; per-owner cap 10 (atomic, counts disabled); world/run id
sha256 of slot key; lease on store clock (Firestore snap.read_time); cache_namespace = server-random sched_<24 hex>; grant only
budget.request_budget_grant (no person fallback, nothing created without a grant, owner filter in decide); Stop all / Pause all drop L3 -> skip.
Prefilter probed: 14 malformed forms, zero network; a forged token that passes the prefilter (aud is public) still costs one cert fetch.

Still open after 14b (non-blocking now, close before PR 2 sets TILO_SCHEDULE_TICK_* or TILO_SCHEDULES_STORE=firestore):
- Pre-auth cost: tick resolves `runs.run_seams` (and store) as dependencies BEFORE the token check: 5 anonymous 401s built the seams 5 times (probe).
  Today production 503s first (no store/seams wired). Resolve seams lazily after auth.
- Erasure (FR-MEM-09) and consent revoke: nothing disables/deletes a user's schedules; brief snapshot in Firestore is unredacted user text
  (intake has no secret screen). Register `orgs/*/schedules` in the erasure `firestore` store; firestore.rules (none exist) must deny clients.
- Infra PR 2: composite index (enabled, next_due); egress to googleapis.com for the cert fetch (default requests timeout 120 s, no cert cache);
  tilo-api SA Firestore role least privilege; ACCESS.md still says harness for the tick.
- PATCH no-op on the Firestore store: `_update` returns {} and `tx.update(ref, {})` raises ValueError "Cannot update with an empty document" -> 500 (probe).
- run_seams_unwired is a global condition but consumes per-schedule MAX_FAILURES: every schedule disabled after ~8.5 h of unwired seams.
- Policy daily limits count in-memory history only (restart resets); ceiling (deps.budget_cap_ceiling) not re-applied at fire; schedule may pick any
  offered approach, not the one approved; re-enabling an old schedule fires the latest missed slot at once; FirestoreScheduleStore(client=None)
  can build a live client when constructed directly (door is only open_schedule_store); prior_world_id has no consumer yet (check owner when one lands).
- Parked threads: each scheduled run waits at its gate on a daemon thread; no per-owner live-run bound.
- `schedule` still valid in card.answer_channels / world.paused.channel / policy.notify_channel (BQ-AGT14-1 e).

r2 (a7ba44d) PASS flagged: unknown-at-plan assertion removed (terraform test 54 pass), Schedule refuses non-finite/<=0/bool budget_cap.
r1 (6c49214) FAIL: `terraform test` failed at infra/envs/dev/tests/schedule_tick.tftest.hcl:66 (audience/uri unknown at plan under mock_provider).
CI does not run `terraform test`: always run `terraform -chdir=infra/envs/dev test` on infra tickets.

**Why:** the tick is the first unattended starter of runs and now a public route with its own OIDC check.
**How to apply:** on PR 2 (infra retarget) and the erasure/consent ticket re-probe the open list first. Probes in scratchpad: probe_oidc.py (real GoogleOidcVerifier with a counting transport), probe_e2e.py (rig from services/api/tests/_fr_agt_14_lib.py, run with PYTHONPATH=services/api/tests and `-p conftest`). Related: [[t3-invariant-gaps]], [[harness-writer-gaps]].
