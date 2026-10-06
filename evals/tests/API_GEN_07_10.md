# API pinned by the GEN-07..GEN-10 tests (issue #272 (b), Req: GEN-07, GEN-08, GEN-09, GEN-10)

The tests in `test_GEN_07_*.py` .. `test_GEN_10_*.py` are the definition of done; this file is the interface they call.
No contract change is needed: everything is Python and YAML in `evals/`, one prompt folder, and role entries in
`config/models.yaml`. All model calls go through `packages/providers`' `Router`; the module names no model (PL-01).
Reuse `live_e2e.py` (gate, `_Meter`/`_MeteredRouter`, `_Providers`, `_app`, estimate style, redaction) rather than
copying it: the generator's live run of a brief is the same real pipeline.

## Files

| Path | What |
| --- | --- |
| `evals/src/tilo_evals/generator.py` | `run_generate`, `render_report`, `GenerateRefused`, report types. |
| `evals/src/tilo_evals/__main__.py` | New subcommand `generate`; `main(argv, *, environ=None, live_provider_factory=None, safety=None)`. The extra keywords are used by `generate` only and ignored by `run` and `bank`. |
| `evals/generator.yaml` + `evals/generator.schema.json` | Generator settings and their own JSON Schema (an evals-local schema like `bank.schema.json`). **Why here:** `contracts/evals.schema.json` has `additionalProperties: false` (top level and `credit_cap`), so the cap cannot go in `config/evals.yaml` without a contract change. Required keys: `max_inr` (number > 0; the real file says `150`, user-approved per-run cap) and `inr_per_usd` (number > 0). Other keys are optional; the tests write files holding only these two. |
| `prompts/generator/*.md` | The generator's prompt templates (PL-04), loaded with `load_prompt`; a plain line of a template must reach the model. |
| `config/models.yaml` | New roles `generator` and `autorater` (any slug is a valid role). Only that file is pinned; add them to `models.gemini.yaml` / `models.nim.yaml` too if those are used live. |
| `evals/generated/<date>/<id>.yaml` | Output, one file per kept case, plus the report. |

There is no INR rate in the repo; `inr_per_usd` in `evals/generator.yaml` is the one in use (the builder picks it and
notes the source and date in a comment). Cap in credits = `max_inr / inr_per_usd / credit_usd`, `credit_usd` from the
prices file (`config/prices.yaml`, PRD 14.1, today 0.005): INR 150 at a rate of 100 is 300 credits.

## Command

`uv run python -m tilo_evals generate --n N [--dry-run] [--max-inr X] [--settings P] [--bank-dir D] [--out-dir D]
[--models-file P] [--prices-file P] [--report-md P] [--date YYYY-MM-DD]`

* `--n` required, integer >= 1 (0 or negative: exit 2). `--max-inr` overrides the file's `max_inr`.
* Defaults: `--settings evals/generator.yaml`, `--bank-dir evals/bank`, `--out-dir evals/generated`, models and prices
  files as `live_e2e` (`resolve_models_path`, `config/prices.yaml`), `--date` today UTC, `--report-md
  <out-dir>/<date>/report.md`.
* Gate (looked at first, before any provider, screen or file): refused with exit 2 and a stderr line naming the cause
  (contains `LIVE`, or the marker `CI` / `K_SERVICE` / `CLOUD_RUN_JOB`) unless `LIVE` is exactly `"1"`; refused when
  `CI`, `K_SERVICE` or `CLOUD_RUN_JOB` is set, in the `environ` mapping the caller gave **or** in `os.environ`. A
  `--dry-run` is only tested with `LIVE=1` (whether it needs the switch is not pinned).
* Output on stdout, in this order: first line `estimate credits_low=<x.xxxx> credits_high=<x.xxxx> cap=<x.xxxx>`
  (cap in credits, same shape as `live_e2e`), printed **before the first model call** (and alone, with exit 0, for
  `--dry-run`, which builds no provider, calls no screen and writes nothing); at the end `total credits=<x.xxxx>
  cap=<x.xxxx>` (what the Router metered, autorater calls included).
* Exit codes: 0 ran, at least one case written, no hard finding; 1 a generated case's hard check failed, or no case
  could be written (also: an unusable generator reply); 2 refused or bad arguments (nothing sent, nothing written);
  3 stopped at the credit cap (stderr line contains `cap`; nothing over the cap is ever sent: PL-03 Router budget; no
  up-front refusal when the cap is below the estimate).

## `tilo_evals.generator`

```python
GENERATOR_ROLE = "generator"; AUTORATER_ROLE = "autorater"

class GenerateRefused(Exception): code: str            # gate / argument refusals

def run_generate(
    n: int, *, mode: Literal["live", "dry-run"] = "live", max_inr: float | None = None,
    environ: Mapping[str, str] | None = None,          # None: os.environ (the gate reads this mapping AND os.environ for CI markers)
    bank_dir: Path | None = None, out_dir: Path | None = None, settings_path: Path | None = None,
    models_path: Path | None = None, prices_path: Path | None = None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None,   # (role, profile_id) -> the LIVE provider; the test seam, as in live_e2e
    safety: SafetyProvider | None = None,              # the screen for each generated brief; None: built from the `safety` role
    today: datetime.date | None = None, announce: Callable[[Estimate, float], None] | None = None,
) -> GenerateReport
def render_report(report: GenerateReport) -> str       # the markdown the CLI writes to --report-md
def main(...)                                          # in __main__
```

`GenerateReport` attributes: `requested`, `date` (`YYYY-MM-DD`), `cap_credits`, `cap_inr`, `estimate`
(`credits_low`, `credits_high`), `total_credits`, `stopped_at_cap: bool`, `cases: list[GeneratedCase]` (kept and
written: `id`, `path`, `outcome_class`, `findings`), `rejected: list[Rejection]` (`index` = position in the model's
list, `reason`, `detail`), `live_scores: dict[case id, {"plan_fit": float, "question_usefulness": float}]`, and
`hard_findings: list[Finding]` (`tilo_evals.bank_checks` hard findings of the generated runs only; scores never feed it).

### The generator call (GEN-07)

One call of role `generator` through the Router asks for N briefs. Its prompt comes from `prompts/generator/` and is
given the domain x shape matrix (every `domain` and `shapes` value of `bank.schema.json`) and the tags of existing
cases, never bank brief text or titles. The reply is a JSON object (untrusted):

```json
{"briefs": [{"title": "<=120 chars", "domain": "<bank domain>", "shapes": ["<bank shape>", "..."], "brief": "text"}]}
```

### Validation (GEN-08), per entry, in list order; rejection `reason` is one of

* `invalid`: not an object, a missing/empty `title` or `brief`, a `domain` or any `shape` outside the matrix, `shapes` empty.
* `length`: `brief` empty after trimming, or longer than 4000 characters (the bank schema's own limit; exactly 4000 is kept).
* `language`: no letter at all, or a control character other than newline and tab.
* `safety`: flagged by `SafetyProvider.check`, **or** the screen raised (fail closed). Every kept brief was screened first.
* `duplicate`: a near-copy (the tests: an exact copy; a copy changed only in case, spacing and punctuation; a copy with
  one word of a 40-word brief swapped) of a bank brief, of an earlier brief in the same reply, or of a brief in any
  `<out-dir>/*/*.yaml` from an earlier run. An unrelated brief in the same domain is kept. A word-set Jaccard around 0.8 is enough.
* At most N cases are kept, in order. A reply that is not JSON, or has no usable `briefs`, keeps none (exit 1, no traceback).
* A rejected brief is never run: the pipeline's Director is not asked to read it.

### The live run and the file (GEN-09)

Each kept brief runs once through the real pipeline (as `live_e2e` does, with the fake or live provider behind the
Router and the run's Router budget shared with the generator and autorater calls). The file `<out-dir>/<date>/<id>.yaml`
is a bank case (it must load with `tilo_evals.bank.load_bank` and pass `bank.schema.json`, which may be extended
inside `evals/`; extend `BankCase` too): `id` (file stem; unique; not a bank id; pattern is the builder's choice, e.g.
`G-NNN`), `title`, `domain`, `shapes`, `brief`, `director: {brief, approaches, plan}` (the Director's own replies of
that run, redacted with the provider layer's redaction before saving; a reply the run never got is `null`), and
`expect.outcome` (one of the bank's four classes: `completed`, `held_at_gate`, `refused`, `needs_answers`; a run that
ended in an honest Director stop is `refused`). `run_bank(load_bank(<folder>))` and `python -m tilo_evals bank --bank
<folder>` then replay it with `LIVE` unset to the same class, passing every hard check, deterministically, with no use
of `RecordReplayProvider`'s live path.

### Autorater (GEN-10)

For every kept case one call of role `autorater` (through the Router, metered into the same cap). Reply: a JSON object
`{"plan_fit": n, "question_usefulness": n}`, numbers in [0, 1]; anything else, a failing role, or a cap stop leaves the
case unscored. `render_report` order: counts and structural results first (hard findings, outcome classes, cost,
cap), then one heading line containing `live, N=<n>, <date>` (n scored, the run's date) with every score and a
sentence saying they are not counted as passes. No score appears before that heading. Scores never change
`hard_findings`, outcome classes, written files, the exit code, the bank's report or `bank_digest`.

## Not pinned (builder's choice, say what you chose)

Prompt wording; the id pattern; the near-duplicate method and threshold; how the existing cases' tags are summarised;
the autorater prompt (put it in `prompts/autorater/`); whether `--dry-run` needs `LIVE=1`; the INR rate in the file.
