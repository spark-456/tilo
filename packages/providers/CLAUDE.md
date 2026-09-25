# packages/providers — `tilo_providers`

## Purpose
The model provider layer (PRD 6.4): one interface (`ModelProvider`, plus `SearchProvider`,
`SafetyProvider`, `SpeechProvider`, `RenderProvider`, `HandsProvider` per PRD 12.5) that every
other service calls instead of naming a model. Business code asks for a **role** (PL-01).

## Commands
- `uv run --package tilo-providers pytest` — tests (`packages/providers/tests`)
- `uv run python scripts/lint_model_ids.py` — PL-01 lint (also run by `just lint`)
- `just check` — full gate (fmt, lint, typecheck, tests) from the repo root

## Contracts
- Reads: `contracts/providers.schema.json` (`$defs.models`/`$defs.prices`/`$defs.capability`)
  via the generated `tilo_contracts.Providers*` models. Writes: none yet.

## Config
- `config/models.yaml` + `config/prices.yaml` (PL-06) via `tilo_providers.config`.
- `prompts/<role>/<template>.md` (+ optional `.<provider>.md`) via `tilo_providers.prompts`.

## Requirement IDs
- PL-01–PL-07 (6.4), NFR-25 (17.2), FR-CON-13 / PRD 12.5 (`HandsProvider`). Ticket P0-04 ships
  interfaces, config loader, PL-01 lint, prompt loader; adapters land in P0-05, router in P0-06.

## Local rules
- No model id, prompt text or connector secret outside this package and `config/`
  (`scripts/lint_model_ids.py` enforces this on tracked source files).
- Denylisted model ids fail start-up loudly (`ProviderConfigError`, PL-07); so does a role
  naming an unknown profile or missing a fallback (NFR-25 — a role shaped only
  `{primary: ...}` is exempt), and a profile with no price entry.
- `price()` never invents a price: an `unset` price status raises instead of metering (PL-06).
- Interfaces are kept thin (`abc.ABC` + pydantic models); no provider-calling logic here yet.
