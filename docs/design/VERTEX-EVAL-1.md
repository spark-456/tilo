# VERTEX-EVAL-1: live autorater runs on the Vertex AI Gen AI evaluation service

- Status: design, architect, 2026-10-08. The interface decision is ADR-0033. No implementation code.
- Ticket: VERTEX-EVAL-1, user-approved. It adds (a) a pairwise side-by-side comparison over about 20
  recorded cases and (b) a groundedness (hallucination) score, both computed by the Gen AI evaluation
  service, behind the user's `LIVE=1`, capped below 20 credits a run.
- PRD: 6.3 (the service's job: "Autoraters for plan quality and groundedness"), 6.4 (PL-01, PL-04,
  PL-06), 6.6 (EFF-01, EFF-07), 14.1 (1 credit = US$0.005), 16.1 rule 4 (no secrets leave), 19.3
  (autoraters, honest reporting, judge on the strongest profile), OQ-13 (default: custom rubrics).
- Contracts: **no file under `contracts/` changes.** One condition: if the price page bills a fee
  per character, the price row uses ADR-0029's `unit_price` (providers 1.3.0, accepted, not yet on
  `phase0-stack`). That is not a new change.
- Open questions: BQ-VEVAL-1 to BQ-VEVAL-3 at the end of `docs/open-questions.md`.

## 1. Decisions

### 1.1 A new sibling interface, `EvalProvider` (ADR-0033)
The service does not fit `ModelProvider`. One call evaluates one instance against one metric spec and
returns a choice or a score with an explanation. It reports no token usage. The judge model is a
field of the request (`autoraterConfig.autoraterModel`), not the endpoint. Fitting it into
`generate()` would fake `text`, and the router's repair, cascade and fallback would be wrong:
changing judges in the middle of a run invalidates the comparison. So the eval service gets its own
sibling interface, like Model Armor (`SafetyProvider`):

- One role, `eval_judge`, in `config/models.yaml`. It is primary only: the builder reads `primary`,
  never `fallback` (as for `safety`). Its fallback is the same profile, so NFR-25 holds.
- One provider kind, `vertex_eval`. `profile.model` is the judge model the service is told to use.
  It is the only model id, and it lives in config (PL-01).
- The existing `autorater` role (the generator's GEN-10 scores through the Router) is unchanged.

### 1.2 Custom rubrics only, never predefined metrics
The service ignores `autoraterConfig` for predefined metric specs, so it would judge with its own
default model. That model is not in config, has no price and may be denylisted. OQ-13's default is
custom rubrics. Every metric is therefore a `metricPromptTemplate` that we write, kept in
`prompts/eval_judge/` (PL-04). Tilo's metric ids are names for those templates. The service never
sees a metric id.

### 1.3 What is judged: recorded Director output
The only recorded inputs and outputs with a schema are bank-format case files
(`evals/bank.schema.json`: `brief`, `files`, `answers`, `director.{brief, approaches, plan}`). The
same shape holds the scripted bank (`evals/bank/`, 40 cases) and live-captured cases
(`evals/generated/<date>/G-NNN.yaml`). PRD 19.3 names plan quality and groundedness as autorater
jobs, so:

- (a) **Pairwise `plan_pairwise`:** which side's recorded Director output better serves the same
  brief.
- (b) **Pointwise `plan_groundedness`, scored 0 or 1:** 1 only if every factual statement in the
  candidate's output (goal, audience, deadline, constraints, sources, deliverables) is supported by
  the brief, answers and files. A planning decision is not a factual claim. The service returns a
  float; anything but 0 or 1 is an error row.

This is not PRD EV-05, which counts claims supported by a cited source over E-RES. The report calls it
"plan groundedness (live judge)" and never shows it in an EV row (BQ-VEVAL-2).

**Honest gap (BQ-VEVAL-2).** No pre-cost-fix and post-cost-fix recordings of the same cases exist on
disk. The repo has the scripted bank and B-007's synthetic recordings. Model recordings store only
the response, keyed by a request hash, so they cannot be turned into inputs. The command works on any
two bank-format folders over the same briefs. Default for the first live run: baseline = the
committed scripted bank (the reference plans); candidate = a folder captured from live Director runs
of the same cases. That capture is follow-up ticket VERTEX-EVAL-1c, which uses `generator.py`'s
`_CapturingRouter` and is its own live spend, outside this ticket's cap. Until it exists, the live
run judges plan groundedness on whatever single set the user has, and the fake runs everything.

## 2. Layout and size

| PR | Files | Hand-written lines (est.) |
| --- | --- | --- |
| **1a** providers | `tilo_providers/interfaces.py`: `EvalItem`, `EvalRequest`, `EvalScore`, `EvalProvider` (~45). `tilo_providers/evaluation.py`: `EVAL_ROLE`, `FakeEvalProvider`, `build_eval_provider` (~70). `tilo_providers/vertex_eval_adapter.py`, the live REST adapter, mocks only (~110). `conformance.py`: skip `vertex_eval` and `model_armor` profiles, which are not ModelProviders (2). `config/models.dev.yaml`: `eval-fake` profile and `eval_judge` role (4). `config/prices.yaml`: `eval-fake: {input: 0, output: 0}`, "makes no paid call" (1). `packages/providers/CLAUDE.md` (2). | ~235, plus ~220 test lines |
| **1b** evals | `tilo_evals/vertex_eval.py`: gate, settings, export, run, meter, report (~240). `evals/vertex_eval.yaml` (~15) and `evals/vertex_eval.schema.json` (~45), evals-local like `generator.yaml`, because `contracts/evals.schema.json` forbids extra keys. `prompts/eval_judge/plan_pairwise.md` and `plan_groundedness.md` (~45). `__main__.py` wiring (~25). `justfile` `vertex-eval *args` (3). `.gitignore` `evals/vertex-eval/` (2). `evals/CLAUDE.md` (3). | ~380, plus ~380 test lines |

Two PRs, since together they come to more than 400. If 1b runs over, split it into 1b-export and
1b-run/report. Test files sit on `tests/VERTEX-EVAL-1a` and `tests/VERTEX-EVAL-1b`. 1b can start on
1a's fake as soon as 1a's interface has merged.

### 2.1 Interface (PR 1a; thin, pydantic, `extra="forbid"`)
```python
class EvalItem(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    prompt: str
    context: str = ""
    response: str
    baseline_response: str | None = None        # pairwise only; required there

class EvalRequest(BaseModel):
    metric: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    kind: Literal["pairwise", "pointwise"]
    template: str                                # rubric text from prompts/eval_judge/ (PL-04), sent as is
    item: EvalItem                               # one instance a call: one quote, one charge

class EvalScore(BaseModel):
    choice: Literal["candidate", "baseline", "tie"] | None = None   # set iff pairwise
    score: float | None = None                                       # set iff pointwise, finite
    explanation: str = ""                        # already redacted by the provider, at most 500 chars

class EvalProvider(ABC):
    @abstractmethod
    def evaluate(self, request: EvalRequest) -> EvalScore: ...
    def redact(self, text: str) -> str: return text
```
A request whose kind and fields disagree is a `RequestError`. A result whose shape does not match its
kind is a `ProviderError`. Each fails closed: an unusable judgement becomes an error row and is never
replaced by a default.

### 2.2 Builder and fake (PR 1a, `evaluation.py`)
- `build_eval_provider(config, *, live_permitted=False)` reads the `eval_judge` role's primary.
  - `fake` gives `FakeEvalProvider`, refused when `LIVE=1` is set or when `K_SERVICE` or
    `CLOUD_RUN_JOB` is present (presence, even if empty).
  - `vertex_eval` gives the live adapter, imported lazily and refused without `LIVE=1` or
    `live_permitted`.
  - Anything else, or a missing role, is a `ProviderConfigError`.
- `FakeEvalProvider` is deterministic and visibly fake: its choice and score come from
  `sha256(metric|id)`, and its explanation is the fixed text "fake judgement (dev stand-in)".
- There is no record-and-replay provider. The report JSON keeps every judgement, and dev and CI use the
  fake (EFF-01). One obvious shape.

### 2.3 Live adapter (PR 1a, `vertex_eval_adapter.py`; follows `model_armor_adapter.py`)
- Request: `POST https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}:evaluateInstances`
  over `httpx`, with `trust_env=False`.
- Body:
  - `pairwiseMetricInput` or `pointwiseMetricInput`, holding `{metricSpec: {metricPromptTemplate},
    instance: {jsonInstance}}`. `jsonInstance` is `json.dumps` of `prompt`, `context`, `response`
    and, for pairwise, `baseline_model_response`.
  - `autoraterConfig: {autoraterModel: "projects/{p}/locations/{l}/publishers/google/models/{profile.model}",
    samplingCount: 1, flipEnabled: false}`. Both are fixed: no hidden repeat calls, and the
    position is handled in 3.3.
- Response: `pairwiseMetricResult.pairwiseChoice` (`CANDIDATE`, `BASELINE` or `TIE`) or
  `pointwiseMetricResult.score`, plus `explanation`. Field names follow the v1 REST reference, read on
  2026-10-08
  (<https://docs.cloud.google.com/gemini-enterprise-agent-platform/reference/rest/v1/projects.locations/evaluateInstances>).
  The builder confirms the nested names and the custom-metric output format against the docs at build
  time (BQ-VEVAL-3).
- Project: `GOOGLE_CLOUD_PROJECT`. Location: `TILO_VERTEX_EVAL_LOCATION`, default `asia-southeast1`
  (PRD 6.5 and the ADR-0029 price region; BQ-VEVAL-1). Both are checked with full-match patterns, like
  Model Armor's. Once ADR-0029 has merged, `vertex_eval` joins the loader's location-versus-price-region
  check.
- Auth: user ADC bearer only, through a lazy `google.auth.default()` and the existing
  `refuse_service_account_key` (it refuses a key file, or the variable). `transport=` (an
  `httpx.MockTransport`) and `token=` (a callable) are injectable. Without them and without
  `LIVE=1`, construction refuses before `google.auth` is imported.
- Errors: `map_http_status` and `map_transport_error`. A message never carries the token, the request
  or the response body. Response JSON is parsed with duplicate keys refused (Model Armor's
  `_duplicate_key_free`). A missing or unknown choice, a non-finite score or non-JSON is a
  `ProviderError`. `redact()` uses `_GOOGLE_SECRET_RE`, and the explanation is redacted, then capped
  at 500 characters.

## 3. Config, CLI, metering, report (PR 1b)

### 3.1 Config
- **`config/models.yaml`: nothing until the price is confirmed.** `prices.yaml` is `status: set`,
  and the loader refuses any profile without a price, so an unpriced profile would break start-up
  for every service. The user's own step (BQ-VEVAL-1) adds these together:
  ```yaml
  # config/models.yaml (EXAMPLE judge; PRD 19.3: the strongest profile; the user chooses)
  vertex-eval: { provider: vertex_eval, model: gemini-3.8-flash, context: 1000000, caps: [] }
  eval_judge: { primary: vertex-eval, fallback: vertex-eval }   # primary only: one judge per run
  # config/prices.yaml, from the price page, with its date and source
  vertex-eval: { input: <USD per 1M judge input tokens>, output: <USD per 1M judge output tokens, thinking included>,
                 valid_until: <if promotional>, unit_price: { unit: character, per_1k: <fee> } }  # unit_price only if billed per character (ADR-0029)
  ```
  Until then a live run is refused with `config_invalid`, and the refusal prints the lines above.
- **`evals/vertex_eval.yaml`** (with `evals/vertex_eval.schema.json`, `additionalProperties: false`):
  ```yaml
  max_credits: 18          # per run; the CLI refuses any cap above HARD_MAX_CREDITS = 19 (code constant): < 20 always
  max_cases: 20
  assumed_output_tokens: 512   # per judgement, thinking included; the service reports no usage (BQ-VEVAL-3)
  overhead_tokens: 400         # per judgement: the service's own wrapper around the rubric (unknown; BQ-VEVAL-3)
  field_chars: { prompt: 1500, context: 3000, response: 2500 }   # after redaction; longer text ends " [truncated]"
  metrics:
    pairwise: { id: plan_pairwise, template: plan_pairwise.md }
    groundedness: { id: plan_groundedness, template: plan_groundedness.md }
  ```

### 3.2 CLI and exit codes
`uv run python -m tilo_evals vertex-eval export|run ...` (and `just vertex-eval ...`):

- `export --candidate DIR [--baseline DIR] [--candidate-label L] [--baseline-label L] [--max-cases N]
  [--out evals/vertex-eval/pairs.local.yaml]`. Free; no provider is built.
  - It loads each folder with the existing `load_bank` (schema-checked) and pairs cases by `id`.
  - A pair is kept only if `sha256(brief, files, answers)` is equal on both sides. Otherwise the row is
    skipped with the reason `inputs_differ`. A case with a null Director reply is skipped as
    `no_output`.
  - The fields:
    - `prompt` is the brief plus the scripted answers.
    - `context` is the files' text, each under its name, and may be empty.
    - `response` is the compact JSON (`sort_keys`, LF) of `director`.

    Both rubrics see `prompt` and `context`. Pairs are sorted by id, and the first `max_cases` are
    kept.
  - Without `--baseline`, only groundedness rows are written.
  - Labels match `^[A-Za-z0-9 ._-]{1,40}$` and default to `baseline` / `candidate`. Folder paths are
    never written.
  - Exit 0 when written; exit 2 for a bad folder, no pair, or bad arguments.
- `run --pairs P (--fake | --dry-run | live) [--max-credits C] [--groundedness candidate|both]
  [--report-md P] [--report-json P] [--models-file P] [--prices-file P]`.
  - Live is the default mode and needs `LIVE=1`; its models file is `resolve_models_path(env)`
    (`config/models.yaml`).
  - `--fake` is refused with `LIVE=1`. It loads `config/models.dev.yaml` unless `--models-file` names
    another, and resolves `eval_judge` through `build_eval_provider`, which gives the fake. It quotes
    from the price file like a live run: `eval-fake` is 0, so a fake run costs nothing, and tests pass
    a priced `tmp_path` file to exercise the cap.
  - `--dry-run` prints the estimate and how many whole cases fit, builds no provider and sends
    nothing.
  - Default report: `evals/vertex-eval/report.local.md` (git-ignored, like the other `*.local.md`).
  - **Exit codes:** 0 every planned judgement returned; 1 a judgement was unusable, or the provider
    failed (the run stops at the first provider failure: `auth`, `permission`, `quota`,
    `api_disabled`, `location`; codes from `vertex_smoke.classify`); 2 refused or bad input
    (nothing sent, no report); 3 stopped at the credit cap (partial report, EFF-07). A run that
    fits no whole case is refused (2, `cap_too_small`).

### 3.3 Run order, position, metering
- **Gate first,** before any file, config or Google import: `live_e2e._gate(mode, env, None)`.
  Live needs `LIVE` exactly `1`, and is refused in CI (`CI`, `GITHUB_ACTIONS`), when deployed
  (`K_SERVICE`, `CLOUD_RUN_JOB`), with `GOOGLE_API_KEY` or `GEMINI_API_KEY` set, or without
  `GOOGLE_CLOUD_PROJECT`. Then our own cap check: finite, above 0, at most 19. Then settings, then
  `load_providers_config` (prices `status: set`), then the `eval_judge` role and its primary
  profile's price (else 2), then the pairs file.
- **Per case,** pairwise first, then groundedness on the candidate (and on the baseline with
  `--groundedness both`). The whole case is quoted first. If it does not fit what is left of the cap,
  nothing more is sent and the run stops (exit 3). A cap stop therefore always leaves whole cases.
- **Position:** even-index cases send the candidate as `response`. Odd-index cases swap the two texts
  and map the choice back. The report shows the order. One call per case, where `flipEnabled` would
  double the cost.
- **Quote, which is also the charge:**
  `((ceil(B/3) + overhead_tokens) * input + assumed_output_tokens * output) / 1e6`. Add
  `units * per_1k / 1000` when the row has `unit_price`. The result goes to credits through
  `ProvidersConfig.credits` (`credit_usd` from `prices.yaml`; no literal).
  - `B` is the UTF-8 byte count of the rubric with the fields substituted, so a third of a byte per
    token errs high (as in `safety.estimate_safety_tokens`).
  - The service reports no token usage, so the meter charges the quote: the metered total never
    exceeds the cap (≤ 19). The report says the figure is estimated and is to be reconciled against
    the billing export (PRD 14.1).
  - If a future response carries usage, the actual figure is charged and any overrun is recorded in
    full.
- **Worked numbers** (ADR-0029 rates; per case = pairwise plus candidate groundedness; any service
  fee is extra):

  | Judge price (in / out per 1M) | Typical case (pairwise B ≈ 4,400, groundedness B ≈ 3,000) | Whole cases in 18 credits | Worst case (fields at caps) |
  | --- | --- | --- | --- |
  | flash 0.825 / 4.125 (example judge, PRD 19.3) | 0.73 + 0.65 = 1.38 credits | 13 of 20 | 2.01 credits a case, 8 |
  | lite 0.275 / 1.65 | 0.27 + 0.25 = 0.52 credits | 20 of 20 (~10.4) | 0.73 credits a case, all 20 (~14.5) |

  Typical sizes: a rubric of about 1,200 bytes (pairwise) or 1,000 bytes (groundedness), a
  400-character brief, no files, and Director output of about 1,400 characters. Worst case uses
  1,500 + 3,000 + 2 × 2,500 characters.

  With the PRD's strongest-profile judge, about 13 of 20 cases fit under the cap. The cap always
  holds, and the report says how many were judged (BQ-VEVAL-3).

### 3.4 Report (`report.local.md`; `--report-json` gives the same content)
1. **Header:** `LIVE: Vertex AI Gen AI evaluation service`, or `FAKE: deterministic dev stand-in, not
   a measurement`. Then the build hash, the UTC time, the judge profile id and role (never the model
   id), each metric id with its rubric sha256, the pairs file sha256, and the two labels.
2. **Scope sentence (fixed):** a single judge model's live judgements of recorded Director output on
   N pairs. It is not an EV row, not EV-05, and not a claim about any other case.
3. **Counts first (PRD 19.3):** for example "Judged 13 of 20 cases (7 not run: credit cap).
   Candidate preferred in 7 of 13, baseline in 4 of 13, tie in 2 of 13." Then the win rates with
   their counts: 54% (7 of 13), and 64% (7 of 11) excluding ties. Then plan groundedness: grounded
   in 11 of 13. Error rows are listed and kept out of every denominator.
4. **Per-case table:** case, pairwise choice, candidate shown as A or B, groundedness (0, 1 or
   error), truncated fields, and the explanation (redacted, at most 120 characters).
5. **Credits:** metered at quote out of the cap, with US$, the stop reason, and the line "estimated;
   reconcile against the billing export".

The JSON has `"basis": "live_autorater"` or `"fake"`. `metrics.py`, `results.py` and
`evals/results.md` never read it. EV-05 stays "no number" in the metrics report.

## 4. Safety
1. **Redaction before export,** on every string the export writes:
   1. Refuse a field over 100,000 characters (`input_too_large`; the row is skipped). This bounds the
      regex work, and NFKC is never run on large input.
   2. Strip the Cc, Cf, Co and Cs categories, except `\n` and `\t`.
   3. Scrub with `live_e2e._scrub_known(text, env)` (project id, ADC file, gcloud folder, emails,
      phone numbers, `ya29.`, `AIza`, `sk-` and Bearer tokens), then `vertex_smoke._SECRET_RE`
      (labelled secrets such as `key=...`), then `replay._AUTHORIZATION_LIKE_RE`.
   4. Only then cap the field: scrub before cap, so a cut never leaves part of a secret.
2. **Again at run time:** the runner applies the same redaction and caps to every field it reads from
   the pairs file, so a hand-edited file cannot bypass it. Each field is passed through
   `neutralise_marker` for its own fence in the rubric (`<<<RESPONSE ... RESPONSE>>>`), so a field
   cannot close its block or steer the judge's frame.
3. **What leaves the machine:** only the redacted fields, our rubric and the judge's resource name.
   Never environment values, paths, recording keys or labels beyond the user's own. The user can read
   the pairs file before running.
4. **What comes back:** explanations are redacted again and capped before they reach the report. A
   failure prints its code only; for a 400 it adds `scrubbed_server_text`, capped at 200 characters
   (`vertex_smoke`).
5. **No ADC in tests.** The adapter is tested only through `transport=` and `token=`. Every test
   patches `google.auth.default` to raise. The live CLI path is tested only up to the gate, or with
   an injected provider factory.
6. **No side effect:** no outbox, no events, no BigQuery. The only output is the local report. The
   judge can be prompted by the text it reads, but that changes only a report row.

## 5. Ordered test list (test-writer first; IDs in names)
**PR 1a (`packages/providers/tests/test_VERTEX_EVAL_1_*.py`)**
1. `test_VERTEX_EVAL_1_request_kind_and_fields_must_agree`: pairwise without a baseline, or pointwise
   with one, is a `RequestError`; a bad id or metric pattern is refused.
2. `test_VERTEX_EVAL_1_score_shape_must_match_kind`: a choice only for pairwise, a finite score only
   for pointwise.
3. `test_VERTEX_EVAL_1_fake_is_deterministic_and_labelled`
4. `test_VERTEX_EVAL_1_build_refuses_fake_when_live_or_deployed`: `LIVE=1`; `K_SERVICE` or
   `CLOUD_RUN_JOB` present but empty.
5. `test_VERTEX_EVAL_1_build_reads_primary_only`: a different fallback profile is never built.
6. `test_VERTEX_EVAL_1_build_refuses_unknown_provider_or_missing_role`
7. `test_VERTEX_EVAL_1_adapter_refuses_without_live_switch_before_auth`: the patched
   `google.auth.default` is never called.
8. `test_VERTEX_EVAL_1_adapter_refuses_service_account_key_and_bad_location_or_project`
9. `test_VERTEX_EVAL_1_adapter_pairwise_request_body`: the URL, `autoraterModel` from
   `profile.model`, `samplingCount` 1, `flipEnabled` false, the `jsonInstance` keys, and the
   template sent as is.
10. `test_VERTEX_EVAL_1_adapter_pointwise_request_body`
11. `test_VERTEX_EVAL_1_adapter_maps_choice_and_score`
12. `test_VERTEX_EVAL_1_adapter_fails_closed_on_unusable_result`: missing or unknown choice, NaN
    score, duplicate keys, non-JSON.
13. `test_VERTEX_EVAL_1_adapter_maps_http_errors_without_echo`: 400, 401, 403, 404, 429 and
    transport errors; no token or body in the message.
14. `test_VERTEX_EVAL_1_adapter_redacts_and_caps_explanation`
15. `test_VERTEX_EVAL_1_dev_models_file_has_priced_fake_judge_and_conformance_skips_it`

**PR 1b (`evals/tests/test_VERTEX_EVAL_1_*.py`; `tmp_path` folders only)**
16. `test_VERTEX_EVAL_1_live_refused_before_any_read`: `--pairs` points at a missing file and the code
    is still `live_not_enabled`.
17. `test_VERTEX_EVAL_1_live_refused_in_ci_deployed_or_with_api_key_or_without_project`
18. `test_VERTEX_EVAL_1_fake_refused_with_live_switch`
19. `test_VERTEX_EVAL_1_cap_out_of_range_refused`: 19.01, 0, negative, NaN, inf.
20. `test_VERTEX_EVAL_1_settings_schema_refuses_unknown_keys_and_bad_values`
21. `test_VERTEX_EVAL_1_live_refused_without_eval_role_or_price`: exit 2, and the needed lines are
    printed.
22. `test_VERTEX_EVAL_1_export_pairs_by_id_and_identical_inputs`: `inputs_differ`, one-sided cases
    and `no_output` are skipped with their reasons.
23. `test_VERTEX_EVAL_1_export_orders_by_id_caps_cases_and_writes_no_paths`
24. `test_VERTEX_EVAL_1_export_redacts_secrets_and_personal_data`: no planted value appears in the
    written bytes.
25. `test_VERTEX_EVAL_1_export_redacts_before_cap`: a secret across the cap boundary leaves no part.
26. `test_VERTEX_EVAL_1_export_strips_control_format_chars_and_refuses_oversize_fields`
27. `test_VERTEX_EVAL_1_export_is_deterministic_lf`
28. `test_VERTEX_EVAL_1_run_re_redacts_hand_edited_pairs_file`: a recording fake sees no planted
    value.
29. `test_VERTEX_EVAL_1_run_fences_fields_with_neutralised_markers`
30. `test_VERTEX_EVAL_1_run_alternates_position_and_maps_choice_back`
31. `test_VERTEX_EVAL_1_run_quotes_from_prices_file`: the formula, `credit_usd` and `unit_price` come
    from the file.
32. `test_VERTEX_EVAL_1_run_stops_before_a_case_over_the_cap`: exit 3; whole cases only; total ≤
    cap; no call is sent past the stop.
33. `test_VERTEX_EVAL_1_run_stops_at_first_provider_failure`: exit 1, a partial report, the code
    only.
34. `test_VERTEX_EVAL_1_unusable_judgement_is_an_error_row`: exit 1, kept out of denominators.
35. `test_VERTEX_EVAL_1_dry_run_builds_no_provider_and_reports_fit`
36. `test_VERTEX_EVAL_1_report_counts_first_and_labels_mode`: LIVE or FAKE header, scope sentence,
    "N of M" before any percentage.
37. `test_VERTEX_EVAL_1_report_provenance_has_no_model_id_or_env_values`
38. `test_VERTEX_EVAL_1_report_never_touches_ev_rows`: `results.md` and the metrics files are
    unchanged; no import of `vertex_eval` from `metrics` or `results`; `basis` is set.
39. `test_VERTEX_EVAL_1_default_outputs_are_git_ignored`: `git check-ignore` on the default pairs and
    report paths.
40. `test_VERTEX_EVAL_1_no_adc_on_fake_dry_run_or_export`

## 6. What a builder must know
- Never add `vertex-eval` to `config/models.yaml` without its price row in the same change: start-up
  fails for every service.
- `just conformance` would build `vertex-eval` as a ModelProvider. PR 1a makes it skip non-model
  providers.
- Reuse, do not copy: `live_e2e._gate`, `_scrub_known`, `vertex_smoke.classify`,
  `scrubbed_server_text`, `_SECRET_RE`, `replay._AUTHORIZATION_LIKE_RE`, `neutralise_marker`,
  `load_bank`, `refuse_service_account_key`, and Model Armor's `_duplicate_key_free`.
- Write files as bytes (LF). Stop only the PIDs you started. The PL-01 lint must stay green: no model
  id in `evals/`, including tests (use a fake id).
