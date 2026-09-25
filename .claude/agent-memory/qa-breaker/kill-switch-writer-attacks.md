---
name: kill-switch-writer-attacks
description: ST-3a kill switch / outbox-style writer attacks that keep finding bugs - hanging writer, parallel flush order, deep data
metadata:
  type: project
---

Attacks on tilo_api kill switches (ST-3a, FR-HIL-07) that found real defects across rounds 3-4 (2026-09-25):
- Slow/failing writer x 200 policies under one global lock (round 3: 6-7 s). Fixed round 4 with per-world locks + thread pool.
- Writer that HANGS (never raises): `with ThreadPoolExecutor` waits for every future, so Stop all never returns and holds the world lock; every later Stop/Pause on that world queues behind it. No per-call timeout. (round 4)
- Parallel flush through a thread pool breaks the pinned "oldest first per world" ordering: ~30-40 inversions in 100 pending parts, nondeterministic.
- Revoke did not flush its own policy's pending part before new work (spec says it must).
- `data` nested 500 deep -> 500 for owner and viewer (recursion / encoder).

**Why:** builders fix the measured symptom (latency) with concurrency and break ordering/boundedness.
**How to apply:** for any writer/outbox fix, always test hang-forever, order after flush, and same-world second call while first is stuck. Script pattern: scratchpad st3a_r4.py.
