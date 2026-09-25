# packages/metering — `tilo_metering`

## Purpose
Credits and the Treasury (PRD 14.1, 14.5). P8-01a built `MeteringConfig`, `PriceBook`, `PriceQuote`,
`Usage`, `FlagStore`/`InMemoryFlagStore` and the two errors. P8-01b adds `Treasury`: open_run, reserve
(estimate + 15%, run/user-day/org-day caps, replay_only and halted-run refusal), commit, commit_usage,
release, grant, record_usage, run(), an append-only ledger. Daily USD spend caps, alerts and
kill-switch flipping are P8-01c.

## Commands
- `uv run --package tilo-metering pytest` — tests; `just check` — full gate from the repo root

## Contracts and config
- Reads `contracts/providers.schema.json` `$defs.prices` via `tilo_contracts.ProvidersPrices` (strict). No events.
- `config/prices.yaml` (PL-06, owned by S0) stays `status: unset`.
- `config/metering.yaml` does not exist yet (contract change #7, batch CC-SE): `MeteringConfig.load` is a local
  stub; tests use `tests/data/metering.stub.yaml` (PRD 14.1/14.5 demo defaults).

## Requirement IDs
- FR-MTR-01 (part a): credit unit, dated and sourced prices from config, refuse rather than guess, no mutation API.
- FR-MTR-02, FR-MTR-04 (part b): reserve-then-commit with a 15% margin; run, user-day and org-day
  caps; append-only ledger. No daily USD spend caps, alerts or kill-switch flipping (part c).

## Local rules
- No model id, prompt text or secret here (PL-01). No dependency on `tilo-providers`.
- `PriceBook` is immutable: frozen dataclasses, no setters, no environment overrides.
- `quote`/`credits` use the latest version effective at the date, whatever its status, and raise
  `UnpricedError` if it is unset or the price is null; they never fall back to an older price.
- Every price, cap, limit and ratio goes through `errors.number` (int or float, not bool or string, finite).
- Both loaders turn any unreadable, malformed or invalid file into `MeteringConfigError` naming the path.
- `Treasury` validates its own inputs with the same `errors.number` rule: estimates and actuals are
  finite non-negative numbers, ids are non-empty strings, `at` is timezone-aware. It is thread-safe
  (one lock); the ledger is append-only and an entry is never re-priced after it is written.
