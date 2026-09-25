---
name: outbox-st2
description: ST-2 tilo_connectors outbox (FR-AGT-11, FR-CHN-13, SEC-03) security review history, probes and still-open gaps; read before any outbox, connector adapter, Firestore store or dispatch ticket
metadata:
  type: project
---

Branch feat/FR-AGT-11-outbox, worktree .claude/worktrees/agent-ae440af5a9f8c13c2, stacks on feat/P4-01-policy-engine.

- r1 FAIL: re-enqueue same id under new key revived cancelled/sent entry; forgeable grants; static-scan bypasses; no CAS; stuck `sending`; lost transfer on emit failure.
- r2 (2f26757) FAIL: `sending` re-claimable with no lease (concurrent dispatch double-called adapter); pending transfers per instance; emit raise stopped batch; racing enqueue same (world,key) stored both; enqueue TOCTOU; grant unbound.
- r3 (ca85d8f, 2026-09-25) FAIL, 78 tests green. Claim lease, store-resident pending transfers, key uniqueness, per-entry emit catch all landed. Still open: the pending-transfer path has no claim, so it repeats r2's defect one step over: `_dispatch_one` adds pending then emits, and any other instance's `_flush_pending_transfers` snapshots and emits the same one (healthy writer, overlapping tick: 1 send, 2 data.transfer; after an outage, 4 instances: 4). `_finalize_claim("sent")` and `_add_pending_transfer` are separate writes: death between them leaves `sent` with 0 transfers forever.
- r3 non-blocking: batch reads clock once, so later leases are taken already expired (3 adapter calls for 2 entries); lease uses caller clock, not store time; lease not renewed for sends > 30 s and FakeGmail dedupe is per adapter instance (per-instance adapters gave 2 real sends); adapter that always raises stays `sending` forever, retried every tick, not cancellable; Grant binds key only (wrapper sent to another thread/recipients with a live grant); scanner unchanged since r2 (4 bp_*.py bypasses in scratchpad still pass); enqueue validates the live dict before snapshotting it.
- Evidence (approval/policy events) is caller-supplied to enqueue and never read from the event log. Issue #23 (closed) covers only enqueue of non-fresh states.

**Why:** each round's fix for "stuck" or "lost" re-opens concurrency one step over (stuck sending -> unconditional re-claim -> unclaimed transfer flush).
**How to apply:** rerun scratchpad sec_st2_r3.py (D1/D2 transfer dup, X death after sent, S stale batch now, P per-instance adapters, F forever-raising, G grant reuse). A fix needs finalize-sent and pending-transfer in one atomic write, and a lease/claim on emitting each pending transfer (or writer dedupe by outbox_id). The Firestore store ticket must keep all of this transactional. See [[t3-invariant-gaps]], [[policy-engine-p4-01]].
