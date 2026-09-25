---
name: p0-06-router
description: P0-06 role router (EFF-02 cascades, EFF-03 caps, PL-05 conformance) passed cost review cleanly — reference shape for future router/cascade tickets.
metadata:
  type: project
---

P0-06 (packages/providers/src/tilo_providers/router.py, conformance.py) passed on first cost
review (2ba270c, 427 tests green). Good reference shape:

- `Router._candidate_profile_ids` trusts `role.cascade` order from config as cheapest-first (no
  in-router price re-sort) — config authoring owns ordering, `config.price()` (PL-06, see
  [[p0-04-provider-config]]) is the only place cost numbers come from. Acceptable: EFF-02 tests
  (`test_EFF_02_router_cascades.py`) assert cheapest-tried-first behaviourally via scripted
  providers where reaching `mid`/`rich` fails the test, not by checking a numeric ordering.
- EFF-03 caps are enforced in `_setup`/`_prepare_request` *before* the candidate loop — the same
  compacted/truncated-or-refused `effective_request` is reused for every cascade attempt, so
  nothing after the cap check can send an uncompacted request.
- EFF-01/LIVE gate: router never constructs an adapter directly — always through
  `provider_for_profile` (test seam) or `factory.provider_for_role_profile`, which is unchanged
  from the d838fe6 fix in [[eff01-adapter-gate]] (gate lives inside `RecordReplayProvider`/the
  adapters themselves). `just conformance` / `conformance.main()` also routes through that same
  factory function, so it stays replay-by-default too.
- Every `ProviderError` subtype gets an explicit branch in `_single_call`: `RequestError` and
  non-`ProviderError` exceptions propagate (no fallback), `SafetyError` ends the call as
  `outcome="safety_blocked"` (not raised), `QuotaError`/`RetryableError` trigger fallback with a
  logged reason. No bare `except Exception` anywhere in the router.

**Why:** worth recording as a positive example — this is what "cascade really starts cheapest and
logs escalation reasons" + "caps enforced before any send" looks like when done right, useful to
compare future router changes (e.g. if someone adds a new escalation trigger or a new
`ProviderError` subtype) against.

**How to apply:** for future router/cascade diffs, check new escalation paths still log a
`reason` string naming the cause, new `ProviderError` subtypes get an explicit branch (not
swallowed by a broad except), and any new call site into an adapter goes through
`factory.provider_for_role_profile` rather than constructing one directly.
