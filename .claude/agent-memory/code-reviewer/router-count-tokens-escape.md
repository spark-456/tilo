---
name: router-count-tokens-escape
description: Router calls provider.count_tokens (a network call on GoogleAdapter) outside its try blocks; its ProviderError escapes raw with no fallback
metadata:
  type: project
---

P0-06 round 6 (2026-09-25): router wrapped `provider.generate/stream/embed` in try/fallback, but `count_tokens` (used for budget pricing in `_attempt`, cap in `_start`/`_fit_cap`, repair-prompt fit) ran outside them. GoogleAdapter.count_tokens hits the API and maps errors to QuotaError/RetryableError, so a 429 on counting escaped the router raw (not a RouterError, no attempts, no fallback).

**Why:** tests use ScriptedModelProvider/replay whose count_tokens is a local whitespace split, so it never fails.

**How to apply:** when reviewing any router or wrapper, list every provider method it calls (count_tokens, capabilities, price, build_provider), not only the main call, and probe each one raising a ProviderError subtype. Related: [[provider-error-base-class]], [[router-real-factory-path-probe]].
