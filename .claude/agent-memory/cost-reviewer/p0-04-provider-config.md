---
name: p0-04-provider-config
description: What a clean cost-focused pass of packages/providers config/interfaces looked like (P0-04) — reference for future provider-layer tickets (P0-05 adapters, P0-06 router).
metadata:
  type: project
---

Ticket P0-04 (packages/providers, tilo_contracts.ProvidersRole/ProvidersProfile/ProvidersPrices)
shipped only interfaces (ABCs), a config loader, PL-01 lint, and a prompt template loader — no
adapters, no network-capable code, nothing that imports an HTTP/gRPC client. That is the correct
shape for this slice: adapters (google, OpenAI-compatible/NIM, record-and-replay) are deferred to
P0-05, the role router to P0-06.

Key things that made this pass on cost grounds:
- `ProvidersConfig.price()` (packages/providers/src/tilo_providers/config.py) raises
  `ProviderConfigError` when `prices.status != "set"` instead of returning 0 — never invents a
  price for metering.
- Token caps (`max_input_tokens`, `max_output_tokens`) are plain fields on the generated
  `ProvidersRole` pydantic model (packages/contracts-py), so `config.roles["x"].max_input_tokens`
  is already exposed for P0-06's EFF-03 compaction/refusal logic — no extra plumbing needed in
  this slice.
- Startup validation (`_validate_startup_rules`) fails loudly on: denylisted model id glob match
  (PL-07), role naming an unknown profile, missing fallback (NFR-25, with a documented single-key
  `{primary: ...}` exemption), and unknown cascade profile ids — this is where EFF-02's "cascade
  must be logged/validated" concern is satisfied at config-load time, not at call time.
- `scripts/lint_model_ids.py` is stdlib-only, scans `git ls-files`, excludes `config/`,
  `packages/providers/`, `design/source/`, and docs — wired into `just lint`. Worth checking this
  script still runs clean (exit 0) on future provider-layer diffs.

**Why:** future provider tickets (P0-05 adapters, P0-06 router) are where EFF-01 (LIVE=1 gating)
actually becomes testable — this ticket had no live-call surface at all, so the main risk was
config validation gaps (silent zero-price, unvalidated cascade/fallback), not network egress.

**How to apply:** for P0-05/P0-06 reviews, check that adapters gate real network calls behind
`LIVE=1` and that the router (not business code) does the cascade/escalation with a logged reason
per role call (EFF-02), and that token caps from `ProvidersRole` are actually enforced (compaction
or refusal) rather than just present in config (EFF-03).
