---
name: schedule-tick-fr-agt-14
description: FR-AGT-14 scheduled runs (tick route, tilo-schedule-scheduler SA, `schedule` channel) r1 FAIL (6c49214), r2 PASS flagged (a7ba44d); open list for the store/starter/wiring tickets
metadata:
  type: project
---

r2 (a7ba44d) PASS flagged: unknown-at-plan assertion removed (terraform test 54 pass, all three FR_AGT_14 runs execute), Schedule refuses non-finite/<=0/bool
budget_cap (harness FR_AGT_14 101 passed). Residual: static repo test only checks an `audience =` line exists, not audience == target_uri (module HCL is
correct: audience = var.target_uri, uri = target + path); Schedule now raises in the store's due() construction, so the store must skip a bad record, not abort.

r1 (2026-10-06, 6c49214, base phase0-stack) FAIL on one item, security-flagged (new IAM identity + OIDC route + frozen-contract widening).
Blocking: `terraform test` fails in infra/envs/dev/tests/schedule_tick.tftest.hcl:66 ("Unknown condition value": audience/uri come from the
Cloud Run service uri, unknown at plan under mock_provider), and terraform skips runs 2 and 3, the only ones asserting "run.invoker on harness
only". Infra itself is right: in a scratch copy with that assert made plan-known, all three runs and the other 51 pass. CI does not run
`terraform test` (only static tests/repo), so builders miss it: always run `terraform -chdir=infra/envs/dev test` on infra tickets.

What holds: route order 503 (nothing wired) / 401 / 403 / 500 with fixed bodies, types-only logs, no body or query read, claims from the verifier
only, audience from wiring; `schedule` opens nothing (coverage SIGNED_IN allowlist, tests/contracts `broken()` returns OB-01 for schedule on
both instruction and approval paths, probed); cards.py, deps.Channel, links use positive lists; new SA has only run.invoker on harness; replay_only
read before any store read; exceptions propagate (500). Production `app = create_app()` is wired to nothing.

Open (check on the store / starter / wiring tickets, not failed here):
- Route does not check `iss` (gmail_watch.py does, ACCESS.md push bullet requires it); wiring must use google-auth verify_oauth2_token or add the check.
- Schedule.budget_cap unvalidated: NaN, inf, negative, 0 reach RunStart (probe). Validate finite > 0 in Schedule or Ticker, and the starter must bind it to the plan cap.
- Head-of-line: due(now,20) is oldest-first and a failing start releases the claim, so 20 permanently failing schedules (dangling brief after erasure,
  revoked consent) starve all others (probe: 21st never fires in 5 ticks). Needs failure counter/backoff and a per-owner schedule cap.
- _latest_slot: arithmetic jump only when next_due weekday == cadence weekday; a misaligned stale next_due (0001-01-02) costs 5.5 s per schedule
  (x20 = ~110 s vs 180 s attempt deadline). Store must validate next_due; computations after claim are outside the try (claim held until lease, tick aborts).
- Store/starter must: take owner from the signed-in session never a body, verify approved_brief_ref and prior_world_id belong to that owner and org,
  re-derive plan and gates (no carried approvals), start deterministic world id from the key, use server time for the lease, disable schedules on
  user erasure and consent revoke. cache_namespace = schedule_id only (must be server-assigned and unique, or include org/owner).
- `schedule` also valid in card.answer_channels (needs_you/blocked), world.paused.channel, policy.notify_channel (BQ-AGT14-1 e): narrow before any notify consumer exists.
- ACCESS.md first Route-requirements bullet does not name tilo-schedule-scheduler; add a 403 test for it when the Gmail renew/poll and Tasks run routes land.

**Why:** the tick is the first route reachable by four run.invoker identities and the first unattended starter of runs.
**How to apply:** on the wiring/store/starter tickets re-probe the list above first. Probe scripts: scratchpad probe_sched.py (rig from services/harness/tests/schedule_support.py), probe_ob01.py. Related: [[t3-invariant-gaps]], [[harness-writer-gaps]].
