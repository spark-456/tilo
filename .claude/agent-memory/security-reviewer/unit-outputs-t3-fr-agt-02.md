---
name: unit-outputs-t3-fr-agt-02
description: ADR-0018 T3 (FR-AGT-02 executor stores unit outputs, EV-15 in harness validator) r1 PASS flagged (fec3947); open gaps for T4/T5/FR-AGT-10/FR-AGT-13 tickets
metadata:
  type: project
---

T3 r1 (2026-10-06, fec3947, base phase0-stack) PASS, flagged. Harness 655 passed; api FR-CON-10 file 8 passed.

What holds: refs via store.head(scope) (org/world path + owner), parent via store._plan (scoped), keep() before any
artifact event, event data from the store record, label printable + redact-unchanged, screening only from store
screener, MF-06 by build_manifest and store, EV-15 rebuilt on writer takeover (open() replays events).

Open (check on the named tickets):
- Store version numbering vs EV-15 desync: a sibling output refused (MF-06 claim, bad label) or a corrupt retry after
  a parented output was stored leaves X vN unannounced; every later version of X in that world ends the run
  (probe: scratchpad probe_t3b.py, EventRejected "must continue ... as version 2"). Must fix before any runner sets `parent`.
- FR-AGT-10 restart re-announces a version (same idempotency key) -> EV-15 ends the run; FR-AGT-13 retries reuse
  attempt-0 keys, so a retry gets the first try's bytes back.
- run_plan does not bind `scope` org/world to the writer's (T4 must, or add a check).
- archive_head passed is archive.head() (self-anchored; build_manifest says external anchor) and records()/head()
  race with concurrent appends.
- bytes(x) is not exact: a bytes subclass with __bytes__ returning a lying-len subclass passes (use memoryview).
- Orphaned unannounced versions count toward MAX_WORLD (200 MB) until 90-day retention.
- Harness now imports tilo_connectors (outbox + tokens package) only for build_manifest; executor events vis "all".

**Why:** T4 wires the store into tilo-api, so these become reachable there.
**How to apply:** on T4/T5/FR-AGT-10/13 reviews re-probe these first. Related: [[artifact-contract-adr0018-t1]], [[harness-writer-gaps]].
