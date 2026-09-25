---
name: api-st3a-review-patterns
description: Recurring defects in tilo-api ST-3a (kill switch/redaction) rounds -- fixes for latency break ordering, spec rounds extend routes (revoke flush) and builders miss it
metadata:
  type: project
---

ST-3a (FR-HIL-07, FR-HIL-09, SEC-07) went 4+ review rounds; spec lives in services/api/tests/API_ST3a.md and grows each round.

- Round 4: builder parallelised EventWriter.append with a ThreadPoolExecutor across ALL parts, including several parts for the same world, which breaks the spec's per-world oldest-first ordering (and races the fake writer's seq counter). Parallelism across worlds is fine; within one world it must be sequential.
- Round 4 spec added "revoke also flushes pending first"; builder did not add it. Always diff the spec's "as of round N" sentences against every route.
- Source size keeps landing over 400 (routes+deps+events ~533 in round 4) because docstrings narrate review history ("round-4 fix (qa)...").

**Why:** each fix round targets the last finding and introduces a new invariant break.
**How to apply:** on a re-review, grep the spec for "round N" and check each route, and check any new concurrency for per-stream ordering.
