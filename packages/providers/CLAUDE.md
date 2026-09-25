# packages/providers — `tilo_providers`

## Purpose
The model provider layer (PRD 6.4): one interface (`ModelProvider`, plus `SearchProvider`,
`SafetyProvider`, `SpeechProvider`, `RenderProvider`, `HandsProvider` per PRD 12.5). Business
code asks `router.Router` for a **role** (PL-01) — never a model or profile id.

## Commands
- `uv run --package tilo-providers pytest` — tests (`packages/providers/tests`)
- `uv run python scripts/lint_model_ids.py` — PL-01 lint (also run by `just lint`)
- `just conformance` — PL-05 suite, replay by default; writes `config/conformance/<profile>.json`
- `just check` — full gate (fmt, lint, typecheck, tests) from the repo root

## Contracts
- Reads: `contracts/providers.schema.json` (`$defs.models`/`$defs.prices`/`$defs.role.cascade`).
  `$defs.profile` (1.1.0) if/else (base_url/api_key_env, openai_compat only) is hand-checked in
  `config._validate_profile_endpoint_fields` (pydantic skips JSON Schema if/else).

## Config
- `config/models.yaml` + `config/prices.yaml` (PL-06); `TILO_MODELS_FILE` swaps in
  `config/models.nim.yaml` (ADR-0003). `prompts/<role>/<template>.md`; `LIVE=1` goes live,
  `+TILO_RECORD=1` records.
- `config/conformance/<profile>.json` (PL-05, own shape): `load_providers_config(...,
  conformance_dir=...)` refuses a role whose primary/fallback/cascade profile fails; a missing
  result only warns unless `TILO_REQUIRE_CONFORMANCE=1`.

## Requirement IDs
- PL-01–PL-07 (6.4), NFR-25 (17.2), EFF-01/02/03 (6.6), FR-CON-13/PRD 12.5. P0-04: interfaces,
  config, prompts. P0-05: adapters, `fake`, `replay`, `factory`. P0-06: `router`, `conformance`.

## Local rules
- No model id, prompt text or connector secret outside this package and `config/`.
- Denylisted ids fail loudly (PL-07); every role needs a fallback (NFR-25); `price()` never
  invents a price (PL-06); `LIVE=1` gate lives in every adapter, not only `factory`.
- `Router`: every `ProviderError` subtype has its own branch. Quota/Retryable/base fall back;
  `RequestError` and bugs propagate; `SafetyError` is `safety_blocked` (generate) or re-raised.
  `stream()` (a `RouterStream` with `.attempts`) falls back only before its first chunk, then
  raises `StreamInterruptedError`. Budget is priced before every call; escalations log a
  `reason`; over-cap input is compacted or refused. Repairs add the validation error
  (`prompts/router/`); `safety_handling` passes only on `SafetyError` (`prompts/conformance/`).
