---
name: outbox-st2
description: ST-2 tilo_connectors outbox (FR-AGT-11, FR-CHN-13, SEC-03) security review history, probes and still-open gaps; read before any outbox, connector adapter, Firestore store or dispatch ticket
metadata:
  type: project
---

Branch feat/FR-AGT-11-outbox, worktree .claude/worktrees/agent-ae440af5a9f8c13c2, stacks on feat/P4-01-policy-engine.

- r1 FAIL: re-enqueue same id under new key revived cancelled/sent entry; forgeable grants; static-scan bypasses; no CAS; stuck `sending`; lost transfer on emit failure.
- r2 (2f26757, 2026-09-25) FAIL, 70 tests green. r1 cases closed, but the claim is not exclusive: `_CLAIMABLE_STATES` includes `sending`, so CAS sending->sending lets every concurrent dispatch_due (second instance, overlapping tick) call the adapter for a live send; no lease/owner/claimed_at. Exactly-once then rests on adapter dedupe, which FakeGmail does non-atomically (check then insert, no lock): stock FakeGmail double-sent 1 in 800 runs; adapter with latency gave 4 sends, 1 transfer.
- r2 also open: pending transfers live in the Outbox instance dict, so emit failure or death after CAS `sent` loses the data.transfer for good on restart (sent, 0 transfers; HR/PI-17). Emit raise stops the batch (API "Failures" says never). Racing enqueue same (world,key) different ids inserts both (`_insert_if_absent` checks id only): 1 send, 2 transfers. enqueue re-reads caller's live `entry` dict after check_entry (TOCTOU). Grant verifies identity only, not bound to thread/recipients/key (wrapper adapter sends elsewhere). Scan misses `getattr(g, n)` with a variable, concatenation, `vars(...)["send_reply"]`, and `_LIVE_GRANTS`/`Grant(` use outside outbox.py. Permanent adapter error: `sending` forever, no backoff, not cancellable.
- Evidence (approval/policy events) is caller-supplied to enqueue and never read from the event log; single-use instruction (earlier_applied) is therefore caller-asserted. Issue #23 covers only enqueue of non-fresh states.

**Why:** each round's fix for "stuck" or "lost" re-opens concurrency one step over (stuck sending -> unconditional re-claim).
**How to apply:** rerun scratchpad probe_st2_r2.py pattern (P1 restarted instance, P2 slow adapter x4 dispatchers, P4 racing enqueue with slow check_entry). A fix needs a lease (claimed_by + claimed_until) on `sending`, durable pending transfers in the store, key uniqueness in `_insert_if_absent`. See [[t3-invariant-gaps]], [[policy-engine-p4-01]].
