# packages/metering — `tilo_metering`

## Purpose
Credits and the Treasury (PRD 14.1, 14.5): a versioned, immutable price book, the metering
config, and the flag store the kill switch (NFR-24) and claims-freeze (P8-04) use. P8-01a
builds the package skeleton only — `MeteringConfig`, `PriceBook`, `PriceQuote`, `Usage`,
`FlagStore`/`InMemoryFlagStore` and the two error types. The `Treasury` (reserve/commit/
release/grant, the ledger, the caps and the kill switch) is P8-01b/c.

## Commands
- `uv run --package tilo-metering pytest` — tests (`packages/metering/tests`)
- `just check` — full gate (fmt, lint, typecheck, tests) from the repo root

## Contracts
- Reads: `contracts/providers.schema.json` `$defs.prices`, via `tilo_contracts.ProvidersPrices`
  (`PriceBook.load` validates every prices file against it). No event contract dependency.

## Config
- `config/prices.yaml` (PL-06; owned by S0, already lands with `status: unset`).
- `config/metering.yaml` does not exist yet (contract-change issue #7, S0's batch CC-SE):
  `MeteringConfig.load` takes an explicit path and is a **local stub** until then. Tests use
  `packages/metering/tests/data/metering.stub.yaml` (PRD 14.1/14.5 demo defaults) in place of
  the repo path.

## Requirement IDs
- FR-MTR-01 (this ticket, part a): credit unit, prices from config with date and source,
  refuse rather than guess, no mutation API.

## Local rules
- No model id, prompt text or secret here (PL-01). No dependency on `tilo-providers`.
- `PriceBook` is immutable: frozen dataclasses only, no setters, no environment overrides.
- `PriceBook.quote`/`credits` raise `UnpricedError` rather than falling back to a guess.
- `MeteringConfig.load` raises `MeteringConfigError` on a missing file, an unknown key, an
  out-of-range value, or `daily_usd_hard < daily_usd_soft`; it never invents a default.
