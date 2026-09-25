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
- r4 (db4f24a, 2026-09-25) FAIL, 81 green. r3 items closed (atomic `_finalize_claim` sent+pending; leased `_claim_oldest_pending_transfer`; clock per claim). New: store.py:135 `_discard_pending_transfer` only pops while the caller still holds the lease. An emit stalling past `_LEASE_SECONDS`=30 lets another tick steal it: plain writer gives 2 data.transfer for 1 send; a writer enforcing PI-17 (rejects 2nd transfer per outbox_id) leaves the already-emitted transfer pending forever, and since order is global (not per world) every later transfer in every world is never emitted while sends continue (probe: 3 sends, 1 transfer).
- Still-open follow-ups (non-blocking so far): per-instance adapter dedupe (lease expiry or timeout-after-accept + another instance = 2 sends; real Gmail adapter needs durable dedupe); Grant subclass overriding `verify` and `_LIVE_GRANTS.add` both send (adapter should use `type(g) is Grant` + module-level verify); scanner misses variable getattr, `+` concat, `vars(...)[...]` subscript, `_LIVE_GRANTS`/`Grant(` outside outbox.py; permanent adapter error = `sending` forever, retried every tick, not cancellable, no backoff/limit; store trust boundary (raw `_insert_if_absent` skips check_entry, dispatch never re-checks; outbox.rules.md says the harness writes entries, service CLAUDE.md says connectors is the only writer: Firestore store ticket must resolve); evidence caller-supplied, not read from event log.

**Why:** each round's fix for "stuck" or "lost" re-opens concurrency one step over (stuck -> re-claim -> unclaimed emit -> lease steal on emit).
**How to apply:** rerun scratchpad sec_st2_r4.py / sec_st2_r4b.py (lease steal by advancing ManualClock 31 s inside a slow emit/adapter, strict PI-17 writer, per-instance adapters, poison transfer). Any lease design must make the post-side-effect bookkeeping holder-independent (an emitted transfer is always discarded). See [[t3-invariant-gaps]], [[policy-engine-p4-01]].
