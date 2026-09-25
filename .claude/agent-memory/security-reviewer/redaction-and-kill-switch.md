---
name: redaction-and-kill-switch
description: ST-3a (FR-HIL-07 kill switches, FR-HIL-09/SEC-07 redaction in services/api) review history and the side channels that keep leaking hidden counts; check on any view/redaction, harness writer or kill-switch ticket
metadata:
  type: project
---

ST-3a review history (2026-09-25):
- Round 1 FAIL: no world membership on reads; fake run_id/self-computed seq; Stop all half-applied with a 500 (KeyError on policy_worlds); pause channel unvalidated; seq gaps leaked hidden counts; policy.changed always vis "all"; 404/403 oracle.
- Round 2 (9753f6c) FAIL: those closed. Still leaking in GET /worlds/{w}/events: `trace.archive_ref`, `data.message_ref`, `policy.applied.data.instruction_id`, real ids. Writer raising mid Stop all -> 500 half-applied. policy.changed vis named districts outside the world layout (EV-13).
- Round 3 (73e3970) FAIL: those closed (allowlisted view, v{seq} ids, pending_events + flush, lock, vis = scope ∩ layout). New biggest: routes.py pause_world emits world.paused only `if stopped > 0` (builder's way to pass the concurrent-pause "exactly one world.paused" test) -> Pause all after Stop all, or an owner with only L0/L1 policies, returns `paused: true` with no event and no store flag: agents never stop (STOP AUTOPILOT then PAUSE on WhatsApp is the natural panic sequence). Also still leaking hidden district ids: `vis` list (["D1","D7"] shown to a D1 viewer), `policy.applied.data.district`, `target` = district id on a vis "all" event; `district` field itself is nulled (fix-one-field pattern again). Nested data (lists/objects) not redacted. Parts pended under another world (policy_worlds) are not counted in `pending` (200 with 0) and never flushed from the requesting world. Revoke with writer down -> 500, event lost, no pending (spec put it out of scope).

**Why:** SEC-07 acceptance is "scoped users never receive hidden names or counts"; PRD 10.1 "fog with no names or counts"; district ids are `D<n>` so an id is a count. Each round the builder fixes the named field and leaves another field with the same meaning. On kill switches, builders satisfy a concurrency/idempotency test by gating the safety action on "did anything change", which turns a repeat press into a no-op. Same pattern as [[t3-invariant-gaps]].

**How to apply:** For any scoped view, enumerate every event.schema.json field and every events/data/*.schema.json field that is a ulid, archive_ref or district_id (vis, target, actor, data.district included) and ask whether it counts or names hidden things. For any kill switch, press it twice and after the sibling switch, and with zero eligible policies; check a durable record exists each time. Probe: scratchpad probe_st3a_r3.py.
