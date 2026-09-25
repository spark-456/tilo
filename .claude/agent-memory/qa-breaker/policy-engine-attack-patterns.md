---
name: policy-engine-attack-patterns
description: Attacks that broke tilo_policy (P4-01) - fail-closed normalisation inconsistencies, Python \d accepting unicode digits in timestamp validation, NaN limits
metadata:
  type: project
---

Found on P4-01 (2026-09-25), worth retrying on any policy/outbox/gate code:
- Normalise-vs-check drift: open_gate mapped unknown risk_tier to "T3" for the returned Decision, but the SEC-06 PIN check compared the raw value == "T3", so "t3"/None/"" skipped the PIN yet reported T3 + run.
- Python regex `\d` matches Arabic-Indic/fullwidth digits; a timestamp validator using `\d` accepts them and string ordering then breaks (expired policy never expires, daily cap date prefix never matches).
- NaN in limits.credits disables the cap (comparison with NaN is False).
- Wrong-typed scope (string instead of list) turns `in` into substring match.
- Recipient domain via rsplit("@") accepts "a@evil.com@example.com".


Round 2 (2026-09-25), after the contract-validation layer landed:
- Duplicate policy ids with different limits: selection `min(key=(level,id))` keeps list order on ties, so [A,B] gates at the cap and [B,A] runs. The order of policies changes the decision.
- Per-entry jsonschema validation costs about 2.3 ms per applied part and about 3 ms per policy. 5,000 applied parts means about 11 s per decide, and it grows with lifetime history because the engine filters by day only after validating everything.
- Empty facts.recipients skips the recipient and domain scope entirely; destination is never scope-checked (API.md documents this as an ambiguity).
- JSON Schema `$` also matches before a trailing "\n", so "a@example.com\n" passes email_address. str.lower() maps the Kelvin sign U+212A to "k", so the domain scope accepts it.

**Why:** each is a fail-open path in code that claims fail-closed.
**How to apply:** script decide/open_gate with these inputs first; use packages/policy/tests/_policy_lib.py factories.
