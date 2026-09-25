---
name: outbox-attack-patterns
description: tilo_connectors outbox (ST-2) - in-memory pending state, per-instance adapter maps, unleased pending-transfer flush and lease expiry are where "exactly once" breaks
metadata:
  type: project
---
ST-2 round 2 (2026-09-25) FAILED: pending transfers in instance memory, emit error stopped batch, foreign-config instance marks entries "failed", "sending" re-claimable, overflow on huge undo window.

ST-2 round 3 (2026-09-25) FAILED. Leases + store-resident pending fixed the round-2 repros, but:
- `_flush_pending_transfers` snapshots pending then emits with no claim: 4 instances flushing one pending transfer concurrently emit 4 data.transfer for 1 send (repro D in scratchpad st2_r3.py).
- Lease is wall-clock 30 s: clock advanced past it mid-send (or NTP step forward) lets a second instance with its own adapter send again (2 underlying sends); holder A's finalize then silently drops its emit.
- Adapter raising forever: entry stays "sending", retried every dispatch forever, no attempt cap.
- Still open from round 2: instance without the adapter marks entry "failed"; pending emits out of send order.

**Why:** each fix protected the exact repro path; the neighbouring path (flush vs dispatch, lease vs slow send) got no lock/claim.
**How to apply:** for any "exactly once" store, run N instances concurrently on EVERY store-backed path (flush, retry, finalize), not just the claim. Related: [[api-kill-switch-attack-patterns]].
