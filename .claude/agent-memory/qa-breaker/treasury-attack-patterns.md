---
name: treasury-attack-patterns
description: Metering Treasury (P8-01b) attacks that found bugs - non-UTC `at` bypasses day caps, size overruns, unvalidated record_usage
metadata:
  type: project
---
P8-01b round 1 (2026-09-25) FAILED on:
- `at.date()` instead of `at.astimezone(UTC).date()`: a +08:00 `at` (our region is asia-southeast1) puts spend on the local date, so user-day/org-day caps are bypassed (160 on one UTC day with cap 100). Check both reserve day and ledger `e.at.date()` in `_day_total`.
- Diff 454 non-blank added lines incl. tests (> 400); PR #36 leftovers folded in inflate it.

P8-01b round 2 FAILED on: reserve before UTC midnight, commit after it -> commit counted on the commit's day, reservation checked on the reserve day, so day total 160 vs cap 100 with actual == reservation. Also the promised non-UTC midnight test was not added (builders skip the "plus one test" part).

P8-01c round 1 (2026-09-26): commit-time spend alerts/kill switch summed committed + OUTSTANDING reservations (reused reserve-side total), though spec says "day's committed spend". Repro: reserve big (not committed) + commit tiny -> soft alert burned (later real crossing silent) and hard flips replay_only with $1 committed, reason text lying "$25 committed". Probe: outstanding reservation + small commit, then release.

**Why:** spec says "Days are UTC dates of `at`"; tests only use UTC `at`, so they never catch it.
**How to apply:** on any day-bucketed cap/ledger code (P8-01c daily USD caps, P8-04 reconcile), always probe with a non-UTC tz-aware datetime near midnight. Also check grant overflow to inf, record_usage accepting non-Usage, grant not clearing halted.
