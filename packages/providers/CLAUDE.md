# packages/providers — `tilo_providers`

## Purpose
The model provider layer (PRD 6.4): one interface (`ModelProvider`, plus `SearchProvider`, `SafetyProvider`, `SpeechProvider`,
`RenderProvider`, `HandsProvider` per PRD 12.5) every service calls instead of naming a model; business code asks for a **role** (PL-01).

## Commands
- `uv run --package tilo-providers pytest` — tests; `uv run python scripts/lint_model_ids.py` — PL-01 lint (also in `just lint`)
- `just conformance` — PL-05 suite, replay by default; writes `config/conformance/<profile>.json`

## Contracts
- Reads `contracts/providers.schema.json` (`$defs.models`/`prices`/`capability`/`role.cascade`); `$defs.profile` if/else (`base_url`/`api_key_env`, openai_compat only) is hand-checked by `config`.

## Config
- `config/models.yaml` + `config/prices.yaml` (PL-06); `TILO_MODELS_FILE` selects `models.nim.yaml` (ADR-0003) or `models.dev.yaml`.
- `prompts/<role>/<template>.md` via `tilo_providers.prompts`; `LIVE=1` goes live; `+TILO_RECORD=1` records.
  `just vertex-smoke` (PL-02, `vertex_smoke.py`): one capped call per role on user ADC (`GOOGLE_LOCATION`, default global; no API key), stops at the first failure; `--replay` serves recordings. `just vertex-probe-schema` (`schema_probe.py`): `director_exact` replays the real brief request (`brief_request`, adapter `_config_kwargs`; small cap), on a 400 one variant per suspect field removed, if accepted the real cap (quoted, ceiling 2 credits); then seven tiny calls (no schema, json mode, sanitized/raw schema, thinking; `minimal` unmapped vs mapped), same gate, `--dry-run` free. Refused before any client: `GOOGLE_LOCATION` not global/us/eu/region, bad project id, `GOOGLE_VERTEX_BASE_URL` set, service-account key (the variable's file or gcloud's well-known ADC file). the smoke sends no `thinking_level` (Vertex 400s on `minimal`); a 400 prints its scrubbed reason (`rejected`, check it before pasting); `thinking_level` goes only to profiles with `thinking`; google `output_tokens` include thought tokens, a None count is 0.
- `config/conformance/<profile>.json` (PL-05): `load_providers_config(..., conformance_dir=...)` refuses a role whose primary/
  fallback/cascade profile fails; a missing result warns unless `TILO_REQUIRE_CONFORMANCE=1`.

## Requirement IDs
- PL-01–PL-07 (6.4), NFR-25 (17.2), EFF-01–05 (6.6), FR-CON-13 (12.5): P0-04 config, P0-05 adapters, P0-06 router; FR-INT-02: CC-SP-47 safety; FR-MTG-17/-11: `speech.py`, `google_speech_adapter.py`, `voice.py` (`synthesize`, `synthesize_stream`, PCM), `cloud_tts_adapter.py` (Cloud TTS Chirp 3 HD, streamed, `VoiceTiming`; lazy `google-cloud-texttospeech`; the live voice is refused until the PriceBook can charge `character`, `character_metering_ready()`: BQ-MTG11-15), `config/speech.yaml`, `config/voice.yaml` (docs/speech-recording-upload.md).

## Local rules
- Denylisted ids fail start-up loudly (PL-07); every role needs a fallback (NFR-25); `price()` never invents one (PL-06).
- Dev Director (CL-INT-5): `model: fake-director` (`config/models.dev.yaml`) -> `DevDirectorProvider`, deterministic brief, approaches and
  plan-draft (`units`) replies from the input only, tagged "(dev)". Refused (load, build, every call) if `LIVE=1` or `K_SERVICE`/
  `CLOUD_RUN_JOB` is set; `dev_only`, so `run_conformance_suite` refuses it and no result file ever makes it conform (PL-05).
- Adapters map SDK/HTTP errors onto `tilo_providers.errors`; `json_mode`/`.response_schema` map to `response_mime_type`/
  `response_json_schema` (google; a `schema_subset.to_gemini_schema` copy: only Gemini's documented keywords (no `additionalProperties`: Vertex-only adapter), `$ref` inlined, list `type` as `anyOf`; google maps thinking `minimal` to `low`, Vertex 400s on `default`/`pattern`/`maxLength`; never the OpenAPI-subset `response_schema`, which rejects `uniqueItems` and list `type`; a pydantic `ValidationError` while the SDK builds the request is a `RequestError`, class name only) or `response_format` (openai_compat). `openai_compat_adapter` rejects a dirty API key (names the
  env var, never the value); `base_url` must be `https://` (loopback `http://` ok). EFF-04: `usage["cached_tokens"]` only when a provider reported a whole number 0..input_tokens (google: present usage + None count = 0); else the key is absent = unknown, never 0/None. Static parts (system, tools, schema) precede per-call text.
- The `LIVE=1` gate lives in every adapter and `RecordReplayProvider`; only an injected `client=`/`transport=` or `live_permitted=True` (SEC-15, `Router`/`build_provider`, default False, never from env, never records) is exempt. `redact(text)` (default no-op) scrubs a provider's own secret before a recording is written (`replay.redact_strings`).
- `batch` (EFF-05): `BatchProvider` submit/poll/results (item failure is data, same idempotency key = same job, no item runs twice); `FakeBatchProvider` (refused if `LIVE=1` or `K_SERVICE`/`CLOUD_RUN_JOB` is set); `build_batch_provider`: fake -> fake, else `RecordReplayBatchProvider` (same recordings as `RecordReplayProvider`, a miss is an item error, never records); the live switch or `live_permitted` builds `google_batch_adapter` (mocks only, refuses without `LIVE=1`).
- `safety` (CC-SP-47, FR-INT-02, BQ-68): `check()` returns `{flagged, reason}`; adapters implement `_check`, `check` gates the media
  type (`content=`/`mime_type=`: PDF/PNG/JPEG only, else `RequestError`, fail closed). `build_safety_provider` reads only the
  primary, never a fallback: `fake` -> `FakeSafetyProvider` (refused if `LIVE=1` or `K_SERVICE`/`CLOUD_RUN_JOB` is set at all),
  `model_armor` -> `SafetyRecordReplayProvider`, live `model_armor_adapter` (REST `:sanitizeUserPrompt`, ADC bearer, `model`=template id, env `GOOGLE_CLOUD_PROJECT`/`TILO_MODEL_ARMOR_LOCATION`; clean only on NO_MATCH+SUCCESS+every filter ran, else raises; `max_input_tokens` cap -> `RequestError`); reasons are fixed categories, writes atomic, corrupt -> `ProviderError`.
- `Router._candidate` is the one choke point for every candidate touch (build, count_tokens, calls, first chunk): `RequestError`/
  stream-embed `SafetyError` raise (generate: `safety_blocked`), mid-stream -> `StreamInterruptedError`, anything else falls back
  (over budget: never sent). Only `RouterError`s leave, with `.attempts` and `__cause__`. `OutputTruncatedError` (MAX_TOKENS/`length`): no repair and no fallback (same cap, same burn: `RouterExhaustedError`, error as `__cause__`), charged from its usage (`input_tokens`), `classify` -> `truncated`; thinking roles carry a `max_output_tokens` (BQ-PL02-1). The role's `thinking` fills an unset `thinking_level` for a profile that declares the capability (BQ-LE2E-10).
