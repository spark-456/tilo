---
name: outbox-st2
description: ST-2 tilo_connectors outbox (FR-AGT-11, FR-CHN-13, SEC-03) security review history, probes and still-open gaps; read before any outbox, connector adapter, Firestore store, event-writer or dispatch ticket
metadata:
  type: project
---

Branch feat/FR-AGT-11-outbox, worktree .claude/worktrees/agent-ae440af5a9f8c13c2, stacks on feat/P4-01-policy-engine.

- r1 FAIL: re-enqueue revived cancelled/sent; forgeable grants; scan bypasses; no CAS; stuck `sending`; lost transfer on emit failure.
- r2 (2f26757) FAIL: `sending` re-claimable with no lease, concurrent dispatch double-sent; pending transfers per instance.
- r3 FAIL: pending transfers emitted without a claim; sent flag and pending write separate.
- r4 (db4f24a) FAIL: `_discard_pending_transfer` needed the lease holder, so an emit outliving its 30 s lease left a pending transfer forever under a strict writer; global order made it block every world.
- r5 (2ff085b, 2026-09-25) PASS, 83 green, 410 src lines. Discard is holder-independent; delivery is at-least-once to `emit`, with order kept per world. r4b probe now 3 sends/3 written/0 pending.

Follow-ups filed at r5 (none blocking while only FakeGmail + InMemoryOutboxStore exist):
1. Harness writer contract, which is not in contracts/ (PI-17/PI-18 don't say it): the writer must ACK a duplicate data.transfer for an outbox_id as success. A writer that rejects duplicates (for example a PI-17 validator run before append), combined with a lost ack, poisons that world's transfers forever while its sends continue. Probe R5-1: 2 sends, 1 in the stream, 2 pending.
2. The r4 regression test `test_PI_17_an_emit_that_outlives_its_lease...` also passes on the r4 code. It never has A's emit land first while B's emit is the rejected one.
3. (a) Adapter dedupe is per instance: a send lease that expires mid-adapter call, or a timeout after the provider accepted, sends twice across instances. The real Gmail adapter needs durable dedupe and a request timeout shorter than the lease.
4. (b) A Grant subclass that overrides `verify`, or a direct `_LIVE_GRANTS.add`, still sends. The adapter should check `type(g) is Grant` and use a module-level verify.
5. (c) The scanner misses `'send_'+'reply'`, a variable passed to getattr, `vars(T)[...]` and `T.__dict__[...]`.
6. (d) A permanent adapter error stays `sending` forever: retried every tick, not cancellable, with no backoff, attempt cap or escalation (ties to FR-AGT-13).
7. (e) Store trust boundary: a raw `_insert_if_absent` skips check_entry, and dispatch never re-checks. The writer is still ambiguous: outbox.rules.md says the harness writes, the connectors CLAUDE.md says only connectors writes. Claims use the instance clock and the store never re-checks `scheduled_at`, so a skewed instance sends inside the undo window (R5-4). The Firestore store must use server time in the claim transaction.

**Why:** each round's fix for "stuck" or "lost" re-opened concurrency one step over. Exactly-once now depends on two components outside this ticket: an idempotent writer and a durable adapter dedupe.
**How to apply:** for harness event-writer, Gmail adapter or Firestore store tickets, rerun scratchpad sec_st2_r4.py, sec_st2_r4b.py and sec_st2_r5.py (these may need rewriting if the scratchpad is gone) and check items 1, 3 and 7 first. See [[t3-invariant-gaps]], [[policy-engine-p4-01]].
