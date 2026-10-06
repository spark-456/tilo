# ADR-0022: Cached input tokens in the event trace (EFF-04)

- Status: Accepted. The user confirmed on 2026-10-06 an additive, optional `trace.tokens_cached`
  field in `contracts/event.schema.json` (relayed by the supervisor; BQ-EFF04-1). The event
  contract is frozen (CP0, 29 Sep), so this ADR is the gate: **the user should check the
  Decision section below**. Written by the architect on 2026-10-06.
- Deciders: user (approval), architect
- Requirement: EFF-04 (PRD 6.6, Should): "Stable prompt prefixes; cache-hit rate reported where
  the provider supports caching". Acceptance test: "Nightly report includes cache-hit rate per
  role". Related: PRD 9.3 (`trace`), 9.6 (Trace lens), EFF-02, EFF-05, EFF-06, PL-02, PL-03.

## Context
1. PRD 9.3 fixes the trace as `{model_role, profile, tokens_in, tokens_out, tool, latency_ms,
   archive_ref}`. There is no count of cached input tokens, so no report can compute a cache-hit
   rate from events, and events are the only record a report reads.
2. Providers do report the count, each in its own field:
   - Gemini (Vertex AI and the Gemini API): `usage_metadata.cached_content_token_count` (REST
     `cachedContentTokenCount`). `prompt_token_count` already includes the cached tokens.
   - OpenAI-compatible endpoints: `usage.prompt_tokens_details.cached_tokens`. `prompt_tokens`
     already includes them. Many OpenAI-compatible servers, NIM among them, may leave
     `prompt_tokens_details` out.
   - Anthropic: `usage.cache_read_input_tokens`. Here `input_tokens` does **not** include cached
     tokens or `cache_creation_input_tokens`. Tilo has no Anthropic adapter today.
3. Today the provider layer drops the count. `google_adapter.py` and `openai_compat_adapter.py`
   map only input, output and total tokens into `GenerateResponse.usage`; `RouterAttempt` keeps
   `tokens_in` and `tokens_out`; the one emitter that fills a model trace
   (`services/harness/src/tilo_harness/verifier.py::_trace`) sums those two.
4. No nightly job exists yet (EFF-05/EFF-06 will run on Cloud Scheduler). The eval report
   (`evals/src/tilo_evals/results.py`: `results.md` and `--results-json`) already reads each
   event's trace for `cost_per_role`. The nightly job will produce that report, so the rate
   belongs there.
5. `event.schema.json` is still 1.0.0. Every additive change since CP0 has been a minor bump
   with an ADR (ADR-0002 decision 2).

## Decision
1. **The field.** `$defs.trace` gains `tokens_cached`: an integer of 0 or more, **optional**,
   never null. It counts the input tokens the provider served from its prompt cache (cache
   reads), summed over the model calls behind the event. It is a part of `tokens_in`.
   - It is set only when the provider reported a cached count for **every** model call counted
     in `tokens_in`. A reported 0 is a known miss.
   - **Left out means unknown, never zero.** That covers: a provider that reports nothing, an
     adapter that does not map the count yet, an event with no model call, and every event
     written before 1.1.0. Emitters leave the key out. They never write null and never fill in 0.
2. **`tokens_in` is the whole input, cached tokens included.** This is what the Google and
   OpenAI-compatible adapters already report. The description now says so, so that a future
   Anthropic adapter adds `cache_read_input_tokens` and `cache_creation_input_tokens` to
   `input_tokens`. Cache writes are not hits: they count in `tokens_in` only.
3. **Rules.**
   - Schema: `tokens_cached` has `type: integer` and `minimum: 0`. An `if`/`then` inside
     `$defs.trace` makes `tokens_in` an integer whenever `tokens_cached` is present.
   - New rule EV-16 in `contracts/event.rules.md`: `tokens_cached` is at most `tokens_in`. It is
     checked by `scripts/contracts_events.py` (contracts-check) and by the harness validator
     before any write. Both are updated in this change, so the harness parity test (D-11) stays
     green. EV-16 is an event-rule id; PRD 3.5's metric ids end at EV-15 and are a different
     list.
4. **Version.** `event.schema.json` goes from 1.0.0 to **1.1.0** (additive, minor). The envelope
   `v` stays `"1.0"`. No data schema changes. The registry's content and its version (1.1.0) do
   not change: the trace columns are the same for every type, and only the registry's header
   comment now names the cached count.
5. **Old events stay valid.** Every existing fixture, stream, model recording and stored event
   validates unchanged and reads as "unknown". Readers use `trace.get("tokens_cached")` in
   Python and `trace.tokens_cached` (`number | undefined`) in TypeScript, and never default it
   to 0.
   - The generated pydantic field is `int | None = None`, so the model accepts an explicit None
     that the JSON Schema refuses. This is the gap ADR-0011 (still proposed) closes. Until then,
     the harness validator refuses a null `tokens_cached` at write time.
   - `services/api/src/tilo_api/redaction.py` rebuilds a scoped viewer's trace from the seven
     required keys, so scoped viewers do not see the count; for them it is unknown. That is
     safe. Passing it through is a follow-up item.
6. **How adapters fill it.** The seam is `GenerateResponse.usage`: it gains an optional key
   `cached_tokens`, set only when the provider reported a count (the comment in
   `packages/providers/src/tilo_providers/interfaces.py` says so). An adapter sets it only when
   the count is an integer between 0 and `input_tokens`; otherwise it leaves the key out, so
   EV-16 never refuses an event because a provider misreported.

   | Provider | `input_tokens` | `cached_tokens` |
   | --- | --- | --- |
   | `google` | `prompt_token_count` (unchanged) | `cached_content_token_count`. The API leaves a zero count out, so when `usage_metadata` is present and the count is None, the adapter reports 0. It already treats a None thoughts count as 0 (BQ-EFF04-2). |
   | `openai_compat` | `prompt_tokens` (unchanged) | `prompt_tokens_details.cached_tokens` when it is an integer; otherwise left out (NIM often omits it) |
   | Anthropic (no adapter today) | `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` | `cache_read_input_tokens` when it is an integer |
   | `FakeModelProvider`, `DevDirectorProvider` | no usage (unchanged) | left out: unknown. A test may give the fake an explicit usage dict. |
   | `RecordReplayProvider` | replays the recorded usage | as recorded. Older recordings have no key and read as unknown; nothing needs re-recording. |

7. **Router and emitters.** `RouterAttempt` gains `tokens_cached: int | None` (None meaning
   unknown), set in `_usage` from `usage.get("cached_tokens")`. Pricing does not change:
   `_cost` and `_spend` price all of `tokens_in` at the input list price. Credits therefore
   overstate the cost of a cache hit (conservative; BQ-EFF04-3). An emitter that writes a trace
   from model calls sets `tokens_cached` to the sum of the calls' counts only when every call
   it counts in `tokens_in` reported one. Otherwise it leaves the key out.
8. **The rate.** The cache-hit rate of a role is Σ `tokens_cached` ÷ Σ `tokens_in`, over the
   events whose `trace.model_role` is that role and that carry `tokens_cached`. It is weighted
   by tokens, not an average of per-event rates.
   - Events without the count leave both sums and are counted as "unknown".
   - A role with no event carrying the count, or whose known `tokens_in` sum to 0, has the rate
     **unknown** (null in JSON, "unknown" in Markdown), never 0%.
   - The report also shows coverage: the known `tokens_in` as a share of all the role's
     `tokens_in`.
   - This is how "where the provider supports caching" is read: a role is rated wherever a
     provider reported counts (BQ-EFF04-4).
   - The eval report computes the rate per pass. The nightly job (EFF-05/EFF-06) publishes that
     report. A per-call rate from `RouterResult.attempts` uses the same formula (for example in
     the live end-to-end meter).

## Consequences
- An additive contract change: old events, fixtures and replays stay valid. The generated
  Python and TypeScript types gain one optional field each.
- EV-16 is enforced at write time (fail closed), and the adapter clamp in decision 6 keeps a
  provider's own error from rejecting an event.
- Not covered: prices for cached tokens (no field in `config/prices.yaml`), cache-write
  accounting, and explicit context caches (Gemini `CachedContent` resources, which bill
  storage). Each would be a separate decision.
- EFF-04's other half, stable prompt prefixes, needs no contract. Adapters already send the
  system prompt, tool definitions and response schema ahead of the per-call prompt. A builder
  test should pin that order and keep each role's static parts byte-stable between calls.

## Fixtures
- Valid: `fixtures/events/valid/artifact.reviewed--tokens_cached.json` (2,048 of 3,300 cached),
  `agent.working--tokens_cached_zero.json` (a reported miss) and
  `plan.approaches_proposed--tokens_cached_all.json` (equal to `tokens_in`, the EV-16 boundary).
  Every existing valid fixture leaves the field out, which is the backward-compatibility case.
- Invalid (schema): `fixtures/events/invalid/trace_tokens_cached_null.json`,
  `trace_tokens_cached_negative.json` and `trace_tokens_cached_without_tokens_in.json`.
- Invalid (EV-16 only): `fixtures/events/registry/invalid/ev16_tokens_cached_over_tokens_in.json`.

## Follow-up tickets (seams)
1. **EFF-04a, provider layer** (intelligence-builder):
   - `google_adapter.py::_map_response` and `openai_compat_adapter.py::_map_message` map the
     count as in decision 6. Only when a usage chunk carries it does a stream report it.
   - `fake.py` gets an optional `usage=` for tests.
   - `router.py`: `RouterAttempt.tokens_cached` and `_usage`.
   - Tests named `test_EFF_04_*`: count present, zero left out by the API, details missing,
     count above input left out, replay of an old recording reads as unknown.
2. **EFF-04b, trace and report** (evidence-builder):
   - `verifier.py::_trace` per decision 7.
   - `evals/src/tilo_evals/executors.py::_event` refuses a recording whose `tokens_cached` is
     not an integer of 0 or more.
   - `runner.py::_evaluate` collects per role: known `tokens_in`, `tokens_cached`, all
     `tokens_in` and unknown events.
   - `results.py`: a "Cache-hit rate per role" section in `render_section` and
     `cache_hit_rate_per_role` in `render_json` (`{role: {rate, tokens_in, tokens_cached,
     coverage, unknown_events}}`, with `rate` null when unknown).
   - Optionally pass the count through `redaction.py::_allowlisted_trace` when it is a
     non-negative integer.
   - Acceptance test `test_EFF_04_nightly_report_includes_cache_hit_rate_per_role`, over a
     recording that mixes known, zero and unknown events.
