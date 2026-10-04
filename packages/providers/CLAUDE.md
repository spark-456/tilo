# packages/providers — `tilo_providers`

## Purpose
The model provider layer (PRD 6.4): one interface (`ModelProvider`, plus `SearchProvider`, `SafetyProvider`, `SpeechProvider`,
`RenderProvider`, `HandsProvider` per PRD 12.5) every service calls instead of naming a model; business code asks for a **role** (PL-01).

## Commands
- `uv run --package tilo-providers pytest` — tests; `uv run python scripts/lint_model_ids.py` — PL-01 lint (also in `just lint`)
- `just conformance` — PL-05 suite, replay by default; writes `config/conformance/<profile>.json`

## Contracts
- Reads `contracts/providers.schema.json` (`$defs.models`/`prices`/`capability`/`role.cascade`); `$defs.profile` if/else
  (`base_url`/`api_key_env`, openai_compat only) is hand-checked by `config`.

## Config
- `config/models.yaml` + `config/prices.yaml` (PL-06); `TILO_MODELS_FILE` selects `models.nim.yaml` (ADR-0003) or `models.dev.yaml`.
- `prompts/<role>/<template>.md` via `tilo_providers.prompts`; `LIVE=1` goes live; `+TILO_RECORD=1` records.
- `config/conformance/<profile>.json` (PL-05): `load_providers_config(..., conformance_dir=...)` refuses a role whose primary/
  fallback/cascade profile fails; a missing result warns unless `TILO_REQUIRE_CONFORMANCE=1`.

## Requirement IDs
- PL-01–PL-07 (6.4), NFR-25 (17.2), EFF-01–03 (6.6), FR-CON-13 (12.5): P0-04 config, P0-05 adapters, P0-06 router; FR-INT-02: CC-SP-47 safety.

## Local rules
- Denylisted ids fail start-up loudly (PL-07); every role needs a fallback (NFR-25); `price()` never invents one (PL-06).
- Dev Director (CL-INT-5): `model: fake-director` (`config/models.dev.yaml`) -> `DevDirectorProvider`, deterministic brief and
  approaches replies from the input only, tagged "(dev)". Refused (load, build, every call) if `LIVE=1` or `K_SERVICE`/
  `CLOUD_RUN_JOB` is set; `dev_only`, so `run_conformance_suite` refuses it and no result file ever makes it conform (PL-05).
- Adapters map SDK/HTTP errors onto `tilo_providers.errors`; `json_mode`/`.response_schema` map to `response_mime_type`/
  `response_schema` (google) or `response_format` (openai_compat). `openai_compat_adapter` rejects a dirty API key (names the
  env var, never the value); `base_url` must be `https://` (loopback `http://` ok).
- The `LIVE=1` gate lives in every adapter and `RecordReplayProvider`; only an injected `client=`/`transport=` is exempt.
- `redact(text)` (default no-op) scrubs a provider's own secret before a recording is written (`replay.redact_strings`).
- `safety` (CC-SP-47, FR-INT-02, BQ-68): `check()` returns `{flagged, reason}`; adapters implement `_check`, `check` gates the media
  type (`content=`/`mime_type=`: PDF/PNG/JPEG only, else `RequestError`, fail closed). `build_safety_provider` reads only the
  primary, never a fallback: `fake` -> `FakeSafetyProvider` (refused if `LIVE=1` or `K_SERVICE`/`CLOUD_RUN_JOB` is set at all),
  `model_armor` -> `SafetyRecordReplayProvider` (live stub refuses); reasons are fixed categories, writes atomic, corrupt -> `ProviderError`.
- `Router._candidate` is the one choke point for every candidate touch (build, count_tokens, calls, first chunk): `RequestError`/
  stream-embed `SafetyError` raise (generate: `safety_blocked`), mid-stream -> `StreamInterruptedError`, anything else falls back
  (over budget: never sent). Only `RouterError`s leave, with `.attempts` and `__cause__`.
