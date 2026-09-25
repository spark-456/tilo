---
name: api-kill-switch-attack-patterns
description: tilo_api bulk-mutation routes (stop-all/pause/revoke) - fixes keep writer.append inline with lowering; attack with raising, slow and slow-failing writers
metadata:
  type: project
---
ST-3a round 2 (2026-09-25): the apply loop did mutate-then-writer.append per policy; a writer raising at call k half-applied, and two concurrent stop-alls doubled events.

Round 3 (2026-09-25) fixed those with pending_events + a global threading lock, but:
- Lowering and writer.append are still interleaved, and the lock is held across writer calls. A harness that is down behind a 30 ms connect timeout makes 200-policy Stop-all take 6.3-7.5 s (the last policy reaches L1 after ~6.3 s), every retry pays it again (the flush runs before any lowering), and another world's stop-all waits on the same global lock (6.2 s for 1 policy). Spec budget: 5 s "whether the writer is healthy or entirely down".
- Revoke still calls writer.append unguarded: 500, level L1 + history applied, no event, never retried.
- _redact_data is shallow: a hidden event's ULID nested in a data list or dict reaches the viewer.

**Why:** builders fix the exception path and leave the latency path; the fake writers in _api_lib raise instantly.
**How to apply:** always add a TimeoutWriter (sleep then raise) plus a cross-world concurrent call, and time when the Nth policy flips. Script: scratchpad st3a_r3.py. Related: [[eval-harness-recording-validation]].
