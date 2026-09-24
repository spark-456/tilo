# packages/providers — `tilo_providers`

## Purpose
The model provider layer (PRD 6.4): one interface (`ModelProvider`, plus `SearchProvider`,
`SafetyProvider`, `SpeechProvider`, `RenderProvider`) that every other service calls instead of
naming a model. Business code asks for a **role**, never a model id (PL-01).

## Commands
- `uv sync --package tilo-providers` — install
- `uv run --package tilo-providers pytest` — tests
- `just check` — full gate (fmt, lint, typecheck, tests) from the repo root

## Contracts
- Reads: `contracts/` event/schema types once generated (`packages/contracts-py`).
- Writes: none yet (P0-04 adds provider call/response types).

## Config
- `config/models.yaml` (profiles, roles, deny-list), `config/prices.yaml` (PL-06).

## Requirement IDs
- PL-01 through PL-07 (model provider layer, section 6.4). Implemented in ticket P0-04.

## Local rules
- No model id, prompt text or connector secret outside this package and `config/`.
- Denylisted model ids must fail start-up loudly (PL-07).
- Empty scaffold today; do not add provider logic before P0-04.
