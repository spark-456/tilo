# packages/metering — `tilo_metering`

## Purpose
Credits and the Treasury (PRD 14.1, 14.5). P8-01a built `MeteringConfig`/`PriceBook`/`FlagStore`;
P8-01b added `Treasury` (reserve-then-commit, caps, ledger); P8-01c adds daily USD spend caps: a
soft-cap `Alert` once per UTC day, and a hard cap that flips the `replay_only` kill switch (NFR-24)
both on `commit` and pre-emptively in `reserve` when a reservation alone would cross it.

## Commands
- `uv run --package tilo-metering pytest` — tests; `just check` — full gate from the repo root

## Contracts and config
- Reads `contracts/providers.schema.json` `$defs.prices` via `tilo_contracts.ProvidersPrices` (strict). No events.
- `config/prices.yaml` (PL-06, owned by S0) is `status: set` (user-confirmed 2026-10-04); never edit prices here.
- `config/metering.yaml` does not exist yet (contract change #7, batch CC-SE): `MeteringConfig.load` is a local
  stub; tests use `tests/data/metering.stub.yaml` (PRD 14.1/14.5 demo defaults).

## Requirement IDs
- FR-MTR-01 (part a): credit unit, dated and sourced prices from config, refuse rather than guess, no mutation API.
- FR-MTR-02, FR-MTR-04 (part b): reserve-then-commit with a 15% margin, run/user-day/org-day caps, ledger.
- FR-MTR-04 (part c): daily USD spend soft/hard caps and the `replay_only` kill switch (NFR-24).

## Local rules
- No model id, prompt text or secret here (PL-01). No dependency on `tilo-providers`.
- `PriceBook` is immutable: frozen dataclasses, no setters, no environment overrides.
- `quote`/`credits` use the latest version effective at the date, whatever its status, and raise
  `UnpricedError` if it is unset or the price is null; they never fall back to an older price.
- Every price, cap, limit and ratio goes through `errors.number` (int or float, not bool or string, finite).
- Both loaders turn any unreadable, malformed or invalid file into `MeteringConfigError` naming the path.
- `Treasury` validates amounts (`errors.number`) and `at` (timezone-aware); thread-safe; the ledger is append-only.
- FR-MTR-06: `savings.credits_saved` sums `origin_cost - lookup_cost` over `memory.hit` events (id once, never `data.saved`).
- FR-MTR-10: `costs.cost_report` (pure): spend from ledger commits at their recorded credits, never re-priced; by tier (world tier), profile, task type; no model id.
