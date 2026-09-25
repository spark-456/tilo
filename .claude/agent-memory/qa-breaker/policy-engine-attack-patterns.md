---
name: policy-engine-attack-patterns
description: Attacks tried on tilo_policy (P4-01) rounds 1-3 - which broke it, which now hold, and the remaining schema-validation cost per policy
metadata:
  type: project
---

Rounds 1-2 (2026-09-25) broke tilo_policy with: normalise-vs-check drift on risk_tier, Python `\d`
matching unicode digits in timestamps, NaN limits, string scope, "a@evil.com@example.com",
duplicate policy ids making the result order-dependent, JSON Schema `$` accepting a trailing "\n"
email, Kelvin sign lowercasing to "k", empty recipients skipping scope. All fixed by round 3.

Round 3 (2026-09-25): no fail-open found. Held: leap second / 24:00 / 30 Feb rejected, Feb 29 and
year-boundary daily caps, now==expiry gates, equal-timestamp history, near-duplicate ids over 300
permutations, RiskTable dict mutation, IDN vs punycode, uppercase ASCII domain.
Still open: every policy is jsonschema-validated (about 3 ms) BEFORE the cheap action_type filter, so
decide costs about 3 s per 1,000 policies whatever they cover (10k = about 31-37 s).
Minor: negative proposal credits under a credits cap gate with reason l3_daily_cap_reached (fail_closed default).

**Why:** the code claims fail-closed; each earlier finding was a fail-open path.
**How to apply:** re-run the round 1-3 inputs via packages/policy/tests/_policy_lib.py factories on
any change to coverage.py/decide.py; time decide with 1k-10k policies.
