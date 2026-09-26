---
name: outbox-exactly-once-probes
description: ST-2 outbox (tilo_connectors) keeps claiming "exactly once, in send order" for data.transfer without claiming the pending emit; probe with a reentrant emit
metadata:
  type: project
---

ST-2 round 3 (2026-09-25): sends were leased, but pending data.transfer rows in the store were not. `_dispatch_one` adds the pending row, then emits. Any other instance's `_flush_pending_transfers` can snapshot and emit the same row, so it goes out twice. Emitting straight away also skips older pending rows, so a later send's transfer goes out before an earlier one's that is still waiting. The suite's tests only cover a single instance and in-batch order when every emit fails.

**Why:** the builder fixed the round-2 finding (sends claimed twice) for sends only. The same race moved to the emit step.
**How to apply:** on outbox/emit tickets, write a scratch script with an `emit` callback that calls a second Outbox's `dispatch_due()` on the same store (a deterministic stand-in for concurrency). Also make one early emit fail within a batch and check the order of the emits that succeed. Related: [[api-event-emit-patterns]].
