---
name: timeout-then-late-commit-probe
description: Deadline-bounded writer calls that are "abandoned, not cancelled" commit late -> duplicates on flush and out-of-order seq; probe with a writer slow only on call 1
metadata:
  type: feedback
---
When a builder bounds a writer/IO call with a deadline and queues the part as pending on timeout
without cancelling it, the abandoned call still commits later. Result: (a) the part is both in the
store and in pending, so the next flush writes it twice; (b) later parts, submitted while it still
runs, commit before it, so seq order breaks. Tests with writers that either never return or fail fast miss it.

**Why:** ST-3a round 5 (2026-09-25) passed all 75 tests yet a writer slow only on its first call
(0.8s vs 0.5s deadline) gave events [p1, p2, p0, p0].

**How to apply:** For any deadline/timeout + retry-queue design, write a scratchpad probe with a
"late but successful" double and check both duplicates and commit order. Related: [[idempotency-resubmit-probe]].
