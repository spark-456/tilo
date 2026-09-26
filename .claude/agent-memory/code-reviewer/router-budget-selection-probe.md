---
name: router-budget-selection-probe
description: PL-03 "picks by budget" -- router refused outright when primary unaffordable though fallback fit; chaos tests sampled only None/huge budgets
metadata:
  type: project
---
P0-06 round 9 (2026-09-25): Router._charge raised BudgetExceededError on the first unaffordable candidate
(director: large 1.64 credits) with budget=1.0 although fallback medium (~0.41) fit; attempts=[] (no trace).
The chaos property test drew budget from {None, 1e12} only, so the budget path (which deliberately bypasses
the choke point) was never exercised. Also the branch had not merged the current integration base.

**Why:** budget tests only check budget=0 (refuse) and huge (proceed); nothing between prices.

**How to apply:** for routers, probe a budget between the cheapest and dearest candidate's price and check
`git merge-base --is-ancestor <base> HEAD` when the ticket says to merge the base. Related: [[router-count-tokens-escape]], [[router-per-profile-checks]].
