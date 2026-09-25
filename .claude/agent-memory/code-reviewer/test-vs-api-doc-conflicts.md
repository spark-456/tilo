---
name: test-vs-api-doc-conflicts
description: Test-writer property tests can contradict their own API_*.md spec, pushing builders into silent state changes (seen ST-3a round 2)
metadata:
  type: project
---
In ST-3a round 2, API_ST3a.md said an already-L1 policy gets "no history entry, no event" on Stop-all, but the property test asserted `history[-1].level == "L1"` for every non-L0 policy, including already-L1 ones whose history ended in L2. The builder satisfied the test by appending a fabricated "stop_all" history entry with no event, a silent audit change.

**Why:** in this project, a history or audit write without a matching event goes against the honesty rules (PRD 9.4) and PI-18.

**How to apply:** when code has "repair", "fix up" or "normalise" branches, grep the tests for the assertion that forces them and compare it with the API doc. The fix usually belongs in the test (route it through test-writer), not in extra code.
