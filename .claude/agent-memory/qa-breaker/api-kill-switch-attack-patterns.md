---
name: api-kill-switch-attack-patterns
description: tilo_api bulk-mutation routes (stop-all/pause/revoke) - "validate then apply" fixes still interleave store mutation with writer.append; attack with raising and slow writers
metadata:
  type: project
---
ST-3a round 2 (2026-09-25) fixed round-1 half-apply only for malformed *data*; the apply loop still did mutate-then-writer.append per policy.

- Writer that raises on the k-th append: 500, policies 0..k-1 lowered with events, policy k lowered with history but NO policy.changed, rest untouched. Retry counts policy k as already_l1, so its event is never emitted (honesty-rule break).
- Two concurrent stop-alls with a 10 ms writer: 39 events for 20 policies, duplicate history (no lock, TestClient threads reproduce it).
- Principal.districts passed as a str turns `d in principal.districts` into substring matching (leak).

**Why:** builders only fix the repro they were given; injected dependencies (writer, clock) are the untested failure surface.
**How to apply:** for any route that loops "mutate + side-effect call", inject a Flaky writer (raise at call N) and a Slow writer + 2 threads. Script: scratchpad st3a_r2.py pattern. Related: [[eval-harness-recording-validation]].
