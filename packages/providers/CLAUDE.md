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
- Reads: `contracts/providers.schema.json` (`$defs.models`/`$defs.prices`/`$defs.capability`).
  `$defs.profile` (1.1.0): optional `base_url`/`api_key_env`, openai_compat only — an if/else
  the generated pydantic model skips, so `config._validate_profile_endpoint_fields` checks it
  by hand (like `_validate_price_fields_when_set`). Factory reads both off the profile.

## Config
- `config/models.yaml` + `config/prices.yaml` (PL-06); `config/models.nim.yaml` (ADR-0003,
  NVIDIA NIM) selected instead via `TILO_MODELS_FILE` (`config.resolve_models_path`).
- `prompts/<role>/<template>.md` via `tilo_providers.prompts`; `LIVE=1` goes live; `+TILO_RECORD=1` records.

## Requirement IDs
- PL-01–PL-07 (6.4), NFR-25 (17.2), EFF-01 (6.6), FR-CON-13/PRD 12.5. P0-04: interfaces,
  config loader, lint, prompts. P0-05: adapters, `fake`, `replay`, `factory`, `errors`.

## Local rules
- No model id, prompt text or connector secret outside this package and `config/`.
- Denylisted ids fail start-up loudly (PL-07); every role needs a fallback (NFR-25).
- `price()` never invents a price (PL-06); adapters raise unless built with `price=`.
- Adapters map SDK/HTTP errors onto `tilo_providers.errors`; `json_mode`/`.response_schema`
  map to `response_mime_type`/`response_schema` (google) or `response_format` (openai_compat).
- `openai_compat_adapter` rejects a dirty API key (names the env var, never the value);
  `base_url` must be `https://` (plain `http://` only for loopback test servers).
- The `LIVE=1` gate lives in every adapter, not only `factory`/`RecordReplayProvider`:
  `GoogleModelProvider`/`OpenAICompatModelProvider` refuse a real client/transport without it
  — only an injected `client=`/`transport=` (tests) is exempt.
- `ModelProvider.redact(text)` (default no-op) scrubs a provider's own secret before it is
  written; `RecordReplayProvider` calls it, plus an `Authorization`/`Bearer` backstop.
