---
name: redaction-and-kill-switch
description: ST-3a (FR-HIL-07 kill switches, FR-HIL-09/SEC-07 redaction in services/api) review history, the side channels that keep leaking hidden counts, and kill-switch fail-safe gaps; check on any view/redaction, harness writer or kill-switch ticket
metadata:
  type: project
---

ST-3a review history (all 2026-09-25, branch feat/FR-HIL-07-kill-switch-redaction):
- r1 FAIL: no membership on reads, fake run_id/seq, Stop all half-applied with a 500 (KeyError), seq gaps leaked hidden counts, 404/403 oracle.
- r2 (9753f6c) FAIL: archive_ref/message_ref (`<run>/<archive seq>`) and policy.applied.instruction_id leaked hidden counts/ids; writer raising mid Stop all half-applied it.
- r3 FAIL: pause could leave no record; vis/target/actor/nested data leaked hidden districts.
- r4 (9b7b8a6) FAIL: kept `vis:"all"` events with the district nulled, so summary/data.name and event counts leaked (contract fixtures district.created/agent.spawned are vis "all" with district set); locks held across writer I/O (6 s pause); cross-owner lock waits.
- r5 (7a3051c) FAIL, last round under the cap. Redaction now right on structured fields (drop whole event; keys, values, depth 60 fail closed), lock-free writer I/O with 3.5 s/world budget and 0.5 s/part deadline. Blocker: events.py policy_vis `d in world_districts` raises TypeError on a non-string scope.districts entry, after routes.py has popped pending and lowered earlier policies: Stop all 500s with later policies still L3, the backlog (incl. a queued world.paused) is lost, and a later pause returns 200 pending 0 with no world.paused ever written. Spec API_ST3a.md ~line 515 says "no request ever returns 500, whatever shape the matched policies are in".
- r5 follow-ups: a timed-out part is re-queued while its attempt still runs, so a slow harness duplicates every policy.changed/world.paused (parts need an idempotency key; tests' _ALLOWED_PART_KEYS forbids one today); hung attempts leak a thread each; trace copied wholesale (extra keys reach viewers); contract fix filed as spark-456/tilo#29; world-level aggregates (world.planned.unit_count, world.completed counts) and summary free text still count/name hidden work.

**Why:** SEC-07 "scoped users never receive hidden names or counts"; FR-HIL-07/PI-13 Stop all sets every policy to L1 with one policy.changed each. Each round fixes the named field or path and leaves a neighbour with the same effect (another id field, another exception path after the pending pop).

**How to apply:** For views, enumerate every event.schema.json and events/data field that is a ulid, archive_ref or district_id. For kill switches, look for anything that can raise between `pending_events.pop` and dispatch (malformed policy scope, thread start), and time a hung, a slow (0.7 s) and a failing writer. Probes: scratchpad probe_st3a_r5.py and probe_st3a_r5_pause_lost.py (TestClient with raise_server_exceptions=False, run with python -u and os._exit).
