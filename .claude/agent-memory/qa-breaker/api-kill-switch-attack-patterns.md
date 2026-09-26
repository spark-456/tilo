---
name: api-kill-switch-attack-patterns
description: tilo_api bulk-mutation routes (stop-all/pause/revoke) - writer-call dedupe/ordering keeps breaking; attack with slow-then-succeed writers + concurrent callers
metadata:
  type: project
---
ST-3a rounds 2-5 (2026-09-25): half-applied loops, global lock held over writer I/O, unguarded revoke, shallow redaction, late-landing duplicate writes, a thread pool per call.

Round 6 / ST-3a-2 (2026-09-25, dispatch.py `_WorldChannel`) still fails:
- Dedupe by `id(part)` with the entry popped on success: a concurrent call whose snapshot of pending still holds the part resubmits it after the pop -> the same part written 2-3 times (7/20 trials with 16 concurrent revokes after a late landing).
- On a per-part timeout the loop moves on and submits later parts to the 8-worker pool -> later parts commit ahead of the stuck head (deterministic), despite the docstring claiming build order.
- Stale done futures stay in `_in_flight` keyed by id(); after a part dies, a new dict at the same address is treated as written (lost event, ~15% in a direct harness across Store instances).
- Pools are per world, never shut down: +1..8 threads per world, forever (300 worlds -> +300 threads per round).

**Why:** builders fix the exact repro scenario and leave concurrent-caller and timing variants.
**How to apply:** always run a slow-then-succeed writer + N concurrent calls on the same world and count writes per target; check commit order with a slow head. Scripts: scratchpad st3a_r6.py, st3a_r6_idreuse.py (also st3a_r3/r4/r5). Related: [[eval-harness-recording-validation]].
**Why:** builders fix the exception path and leave the latency path; the fake writers in _api_lib raise instantly.
**How to apply:** always add a TimeoutWriter (sleep then raise) plus a cross-world concurrent call, and time when the Nth policy flips. Script: scratchpad st3a_r3.py. Related: [[eval-harness-recording-validation]].
**Why:** builders only fix the repro they were given; injected dependencies (writer, clock) are the untested failure surface.
**How to apply:** for any route that loops "mutate + side-effect call", inject a Flaky writer (raise at call N) and a Slow writer + 2 threads. Script: scratchpad st3a_r2.py pattern. Related: [[eval-harness-recording-validation]].

Round 5 (2026-09-25): per-part deadlines (give up on the future, leave it running, queue pending) create a new bug class. A writer that completes *after* its deadline lands the event AND leaves the part pending, so the next flush writes it twice (duplicate policy.changed). It also lets later parts commit before the late one (world.paused before policy.changed). Hung writer leaks ~1 thread per part per call. Attack any "timeout then retry" design with a writer that is slow-but-succeeds on call 1 only (scratchpad st3a_r5.py).
