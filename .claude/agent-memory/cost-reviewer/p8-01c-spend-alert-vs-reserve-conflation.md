---
name: p8-01c-spend-alert-vs-reserve-conflation
description: daily USD spend cap alerts must count committed spend only, not outstanding reservations — a helper shared between reserve() and commit() alerting can silently conflate the two
metadata:
  type: project
---

In P8-01c (`packages/metering/src/tilo_metering/treasury.py`), the SE-spec (pause/SE-spec.md lines 55-56)
deliberately uses two different totals:
- `reserve()`'s pre-emptive hard-cap check: "day committed + day reserved + amount" (includes outstanding
  reservations — correct, since it is testing whether *making* this reservation would tip the day over).
- `commit()`'s soft/hard alert and kill-switch: "the day's **committed** spend" only (outstanding
  reservations from other steps/runs must not count, since they haven't actually been spent yet).

The reviewed diff implemented both with the same helper, `_day_deployment_total()`, which sums active
(uncommitted) reservations plus committed ledger entries. Used for the alert/kill-switch path, this means
another run's outstanding, never-committed reservation can push `_spend_alerts` over the soft or hard
threshold, firing a false alert and potentially flipping the `replay_only` kill switch (NFR-24) on
spend that was never actually incurred (proved with a standalone repro: r2 reserves $0.50 and never
commits, r1 commits $0.30, soft alert fires at "$0.80" spent against a $0.50 cap; real committed spend
was $0.30).

**Why:** the kill switch existed to protect the *demo's real dollar spend* from crossing a hard cap; if it
can trip on reserved-but-unspent credits it can incorrectly halt the whole public deployment on phantom
spend, which is worse for user trust than under-alerting. This is exactly the kind of confusion PRD 14 /
NFR-24 cost review should catch even though the ticket's own tests never exercised concurrent outstanding
reservations at commit time (all fixtures commit or release before the next reserve).

**How to apply:** for future metering/treasury diffs, check whether "committed" vs "reserved+committed"
totals are computed with the same helper. If a single total is reused across reserve-time admission
control and commit-time alerting, ask for the two to be split (e.g. a `_day_committed_total` vs
`_day_deployment_total`), and write a manual repro (two runs, one leaves a reservation outstanding) since
the acceptance tests are unlikely to cover it. See [[p0-06-router]] for the general pattern of verifying
cascade/cap logic by hand rather than trusting green tests.
