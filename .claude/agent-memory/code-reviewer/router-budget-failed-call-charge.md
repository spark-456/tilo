---
name: router-budget-failed-call-charge
description: PL-03 router deducts a pre-call estimate before sending and never refunds when the call fails (429), so an affordable fallback is refused
metadata:
  type: project
---
P0-06 round 10 (2026-09-26): Router._charge subtracts the estimate from run.budget before provider.generate; a primary
killed with QuotaError keeps its charge, so with budget = 1.5 calls the equal-price fallback is refused
(BudgetExceededError, attempts [a QuotaError, b BudgetExceededError]). The chaos test only checks that
BudgetExceededError is the last attempt, never that the budget was really insufficient.

**Why:** estimate-then-charge with no settle/refund; tests only look at budget outcomes, not at what was spent.

**How to apply:** for budget code, probe "primary fails with a non-billed error + budget covers exactly one call" and
check whether the budget left over matches actual spend. Related: [[router-budget-selection-probe]].
