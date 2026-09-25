---
name: st3a-redaction-killswitch
description: ST-3a (tilo-api kill switches FR-HIL-07/PI-13 and roles/redaction FR-HIL-09/SEC-07) review history, recurring leaks and probes; check on any view/redaction, harness view-writer or kill-switch ticket
metadata:
  type: project
---

ST-3a review history (services/api, branch feat/FR-HIL-07-kill-switch-redaction, all 2026-09-25):
- Round 3 FAIL: pause could leave no record; hidden districts leaked via vis/target/actor/nested data; pending parts for other worlds not counted or flushed.
- Round 4 (9b7b8a6) FAIL. Closed: WorldRecord.paused dedupe, vis from target world, recursive data redaction, cross-world pending count/flush, revoke queues pending.
  - Biggest: FR-HIL-09 acceptance ("a Viewer's API responses never contain hidden-district names") fails on the contract's own fixture shape. district.created and agent.spawned fixtures are `vis: "all"` with `district: D1`, and the summary/data.name carry the district name. routes.py nulls the district id but keeps the event, its summary and data.name, so names leak, and the number of district.created events with a null target gives the hidden count. GET /worlds hides the same districts, so the two routes contradict each other.
  - Also blocking: per-world locks are held across unbounded writer I/O, and flush runs before the level change. With a 3 s writer, a Pause pressed at 0.3 s paused the world at 6.0 s (over FR-HIL-07's 5 s budget), and with no timeout the wait is unbounded. policy_worlds lets owner A's call lock owner B's world, so B's kill switch waited 4 s behind A's writer.
  - Follow-ups: the thread pool scrambles per-world part order (flush order 0,3,5,4,2,1), which puts revoked/stop_all audit events out of order; revoke mutates the policy outside any lock (an unmapped policy takes none); dict keys in data are not redacted; trace is copied wholesale except archive_ref; PauseRequest.channel is client-asserted.

My position on `summary`: PRD 15.3 makes the harness the writer of per-scope views, and free-text scrubbing does not belong in tilo-api. But while tilo-api builds a view from the full stream, it has to fail closed: drop, for a non-owner, any event whose structured fields (district, district-shaped target/actor, data district leaf) name a hidden district, rather than keeping it with the id nulled. The long-term fix is a contract rule (an extension of EV-13: when `district` is set, `vis` is a list that includes it) plus corrected fixtures. That needs an ADR and the user's approval.

**Why:** SEC-07/FR-HIL-09 say no names or counts. Each round nulls the named field but keeps the event, so the same fact leaks through a neighbouring field (summary, data.name, event count).

**How to apply:** Probe with the real contract fixtures (contracts/fixtures/events/valid/district.created.json, agent.spawned.json) for a hidden district, then grep the viewer's JSON for the name and count the events. For kill switches, time how long it takes to reach L1 and paused under a slow writer that then fails, on the same world and across worlds that share policy_worlds. Probe script pattern: scratchpad probe_st3a_r4.py (TestClient + as_principal_by_header + threads).
