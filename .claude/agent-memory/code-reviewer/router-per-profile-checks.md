---
name: router-per-profile-checks
description: Router checks done once for the first candidate (token cap, count_tokens) are not re-applied on fallback/escalation profiles
metadata:
  type: project
---

P0-06 (PL-03/EFF-03) router compacted the prompt against max_input_tokens using only candidates[0].count_tokens; a fallback profile with a different tokenizer was sent over the cap (probe: subclass ScriptedModelProvider with 2x count_tokens, primary raises QuotaError).

**Why:** EFF-03 acceptance is "never silently sent over the cap"; cascades mix providers.
**How to apply:** for any router/cascade change, probe that every per-call guard (cap, budget, capability) is evaluated per profile actually called, not once up front. Related: [[provider-error-base-class]].

Round 6 (c430273): generate/stream fixed, but `Router.embed` still bypasses everything (no RouterAttempt, no budget, returns raw adapter result). Check secondary entry points (embed, batch) get the same instrumentation as generate.
