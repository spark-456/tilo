# packages/providers — `tilo_providers`

## Purpose
The model provider layer (PRD 6.4): one interface (`ModelProvider`, plus `SearchProvider`, `SafetyProvider`, `SpeechProvider`,
`RenderProvider`, `HandsProvider` per PRD 12.5) that every other service calls instead of naming a model. Business code asks for a **role** (PL-01).

## Commands
- `uv run --package tilo-providers pytest` — tests (`packages/providers/tests`)
- `uv run python scripts/lint_model_ids.py` — PL-01 lint (also run by `just lint`)
- `just conformance` — PL-05 suite, replay by default; writes `config/conformance/<profile>.json`

## Contracts
- Reads: `contracts/providers.schema.json` (`$defs.models`/`prices`/`capability`/`role.cascade`). `$defs.profile`
  (1.1.0) if/else (`base_url`/`api_key_env`, openai_compat only) is hand-checked by `config` (pydantic skips it).

## Config
- `config/models.yaml` + `config/prices.yaml` (PL-06); `TILO_MODELS_FILE` selects `config/models.nim.yaml` (ADR-0003).
- `prompts/<role>/<template>.md` via `tilo_providers.prompts`; `LIVE=1` goes live; `+TILO_RECORD=1` records.
- `config/conformance/<profile>.json` (PL-05): `load_providers_config(..., conformance_dir=...)` refuses a
  role whose primary/fallback/cascade profile fails; a missing result warns unless `TILO_REQUIRE_CONFORMANCE=1`.

## Requirement IDs
- PL-01–PL-07 (6.4), NFR-25 (17.2), EFF-01–03 (6.6), FR-CON-13 (12.5): P0-04 config, P0-05 adapters, P0-06 router; FR-INT-02: CC-SP-47 safety.

## Local rules
- Denylisted ids fail start-up loudly (PL-07); every role needs a fallback (NFR-25).
- `price()` never invents a price (PL-06); adapters raise unless built with `price=`.
- Adapters map SDK/HTTP errors onto `tilo_providers.errors`; `json_mode`/`.response_schema` map to
  `response_mime_type`/`response_schema` (google) or `response_format` (openai_compat). `openai_compat_adapter`
  rejects a dirty API key (names the env var, never the value); `base_url` must be `https://` (loopback `http://` ok).
- The `LIVE=1` gate lives in every adapter, not only `factory`/`RecordReplayProvider`: both adapters
  refuse a real client/transport without it; only an injected `client=`/`transport=` (tests) is exempt.
- `ModelProvider`/`SafetyProvider.redact(text)` (default no-op) scrub a provider's own secret before a
  recording is written, plus an `Authorization`/`Bearer` backstop (`replay.redact_strings`).
- `safety` (CC-SP-47, FR-INT-02, BQ-68): `check()` returns exactly `{flagged, reason}`; `check("", content=, mime_type=)`
  screens PDF/PNG/JPEG only, anything else raises `RequestError` (fail closed). `build_safety_provider` reads the
  `safety` role: `fake` -> `FakeSafetyProvider`, `model_armor` -> `SafetyRecordReplayProvider` (live stub refuses).
  Adapters implement `_check`; `SafetyProvider.check` runs the media-type gate. The role never falls back (only `primary`
  is read), a live reason is mapped to a fixed category, recordings are written atomically, a corrupt one is a `ProviderError`,
  and the fake is refused when `LIVE` is 1 or `K_SERVICE`/`CLOUD_RUN_JOB` is set at all (even empty).
- `Router._candidate` is the one choke point for every candidate touch (build, count_tokens, calls, first chunk):
  `RequestError`/stream-embed `SafetyError` raise (generate: `safety_blocked`), mid-stream -> `StreamInterruptedError`,
  anything else falls back (over budget: never sent). Only `RouterError`s leave, with `.attempts` and `__cause__`.
