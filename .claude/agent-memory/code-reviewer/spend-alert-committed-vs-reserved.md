---
name: spend-alert-committed-vs-reserved
description: Treasury daily spend alerts/kill switch reused a committed+reserved helper; probe with a big outstanding reservation plus a tiny commit
metadata:
  type: project
---

P8-01c (2026-09-26): `_spend_alerts` reused `_day_deployment_total` (committed + active reservations) for
"committed spend", so a $0.005 commit with a large open reservation raised soft/hard alerts and flipped
`replay_only`. Spec says alerts/kill switch key on the day's **committed** spend; only reserve()'s
pre-emptive check uses committed + reserved + amount.

**Why:** reusing one aggregation helper for two differently-worded thresholds is the easy slip; tests
only commit with no other reservation open, so they never see it.
**How to apply:** for any cap/alert ticket, open a second reservation before committing a small step
and check the alert's reported spend and any flag flip. See [[router-budget-failed-call-charge]].
