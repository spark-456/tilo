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
- **Needs contract change:** `$defs.profile` has no `base_url`/`api_key_env`, so an
  `openai_compat` profile (`config/models.nim.yaml`) fails the loader (test xfails); adapter
  takes both as constructor args instead.

## Config
- `config/models.yaml` + `config/prices.yaml` (PL-06); `config/models.nim.yaml` (ADR-0003,
  NVIDIA NIM) selected instead via `TILO_MODELS_FILE` (`config.resolve_models_path`).
- `prompts/<role>/<template>.md` via `tilo_providers.prompts`; `TILO_RECORD=1`+`LIVE=1` records.

## Requirement IDs
- PL-01–PL-07 (6.4), NFR-25 (17.2), EFF-01 (6.6), FR-CON-13 / PRD 12.5. P0-04: interfaces,
  config loader, lint, prompts. P0-05: adapters, `fake`, `replay`, `factory`, `errors`.

## Local rules
- No model id, prompt text or connector secret outside this package and `config/`.
- Denylisted ids fail start-up loudly (PL-07); every role needs a fallback (NFR-25).
- `price()` never invents a price (PL-06); adapters raise unless built with `price=` —
  pricing is `ProvidersConfig.price(profile_id)`'s job, not an adapter's (router, P0-06).
- Adapters map SDK/HTTP errors onto `tilo_providers.errors` (Quota/Retryable/Request/Safety).
  `GenerateRequest.json_mode`/`.response_schema` map to `response_mime_type`/`response_schema`
  (google) or `response_format` (openai_compat).
- `openai_compat_adapter` rejects a dirty API key at construction (names the env var, never
  the value); its errors never carry a raw httpx `str()` or unbounded body — key scrubbed.
- `factory.build_provider` never imports an adapter or builds a network client unless `LIVE=1`
  and `TILO_RECORD=1` (EFF-01): dev/CI get `FakeModelProvider`/`RecordReplayProvider`. Tests
  block real sockets; google is tested against a fake at the `google.genai` import path.
