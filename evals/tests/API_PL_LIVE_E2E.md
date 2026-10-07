# API pinned by the PL-LIVE-E2E tests (issue #340, Req: PL-02, PL-03, EFF-01)

The tests in `test_PL_LIVE_E2E_*.py` are the definition of done; this file is the interface they call. Do not rename.
No contract change is needed: everything is Python in `evals/` (the evals lane owns the bank runner) plus one justfile
recipe. All model calls still go through `packages/providers`; the module names no model and builds no Google client.

## Files

| Path | What |
| --- | --- |
| `evals/src/tilo_evals/live_e2e.py` | `run_live_e2e`, `main`, constants, `LiveE2ERefused`, report types. Importable with no Google library loaded. |
| `evals/scripts/live_e2e.py` | Thin entry point: `raise SystemExit(main())`. `--help` works with no live switch. |
| `justfile` | `live-e2e *args:` runs `uv run python evals/scripts/live_e2e.py {{args}}`. |
| `evals/bank/live/<case id>/model-recordings/<role>/<key>.json` | Recordings (provider layer's layout). Never a folder called `recordings/` (gitignored). `B-007` is committed. |
| `prompts/<role>/...` | New prompt templates the run needs (e.g. writer unit, lead review, narrator), loaded through `load_prompt` (PL-04). |

## Module `tilo_evals.live_e2e`

```python
DEFAULT_MAX_CREDITS = 40.0     # US$0.20
HARD_MAX_CREDITS = 200.0       # a larger or non-positive/NaN/inf --max-credits is refused (code cap_out_of_range), every mode
STAGES = ("intake", "approaches", "plan", "run", "narrate")
OUTCOME_CLASSES = frozenset({"completed", "held_at_gate", "needs_answers", "refused", "failed", "stopped_at_cap", "replay_miss"})

def default_recordings_dir(case_id: str) -> Path   # <repo>/evals/bank/live/<case_id>

class LiveE2ERefused(Exception):   # a precondition failed; nothing was sent
    code: str                       # see "Codes"

def run_live_e2e(
    case_id: str = "B-007", *,
    mode: Literal["live", "replay", "dry-run"] = "live",
    max_credits: float = DEFAULT_MAX_CREDITS,
    environ: Mapping[str, str] | None = None,        # None: os.environ. The gate reads ONLY this mapping
    bank_dir: Path | None = None,                    # default evals/bank
    models_path: Path | None = None,                 # default: resolve_models_path (config/models.yaml)
    prices_path: Path | None = None,                 # default config/prices.yaml
    recordings_dir: Path | None = None,              # default default_recordings_dir(case_id); the Router's `fixtures_dir`
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None,   # (role, profile_id) -> the LIVE provider
    safety: SafetyProvider | None = None,            # None: built from the `safety` role like the API does
) -> LiveE2EReport
def main(argv: list[str] | None = None, *, environ=None, live_provider_factory=None, safety=None) -> int
```

* `live_provider_factory` is the test seam. Default: the Google adapter on Vertex (ADC only, project from
  `GOOGLE_CLOUD_PROJECT`, location `GOOGLE_LOCATION` default `global`), built lazily and only for a call that goes live.
  In live mode every (role, profile) gets the provider layer's `RecordReplayProvider` wrapping `live_provider_factory(role, profile)`;
  in `--replay` and `--dry-run` it is never called and never built.
* The run is the real pipeline (the same routes, planner, executor, policy engine and outbox as `tilo-api`), not a
  second implementation. No case id is named in code. The case's `director` data is NOT used by the live module (only
  the fake provider in the tests reads it); the module uses the case's `brief`, `files`, `answers`, `approve`, `gates`
  and `stop_after`, and the GEN-a checks use `expect`.
* In live mode the response is redacted (secrets, emails, phone numbers) BEFORE the run uses it and before it is saved.

### Report (`LiveE2EReport`)

Attributes: `case_id`, `mode`, `outcome_class` (one of `OUTCOME_CLASSES`), `reason` (str | None; for `stopped_at_cap` it
contains the word "cap"), `rows` (list of `Row`: `stage`, `role`, `profile`, `calls`, `tokens_in`, `tokens_out`,
`credits`, `latency_ms` (sum over the row's calls)), `total_credits`, `cap_credits`, `estimate` (`credits_low`,
`credits_high`), `events` (the emitted events, in order), `event_count`, `findings` (list of
`tilo_evals.bank_checks.Finding`), `checks_run` (names of every GEN-a check applied), `questions` (int asked),
`answered` (dict field -> answer sent, from the case), `story_lines` (list with `.text`, `.event_ids`),
`side_effects` (the string `"mock_only"`: the run's delivery and gated send go to the recording mock connectors, never a
real mailbox, chat or Drive; any real side effect needs the user's separate say-so), and `to_dict()`.

* One call is counted in exactly one row; `total_credits` = sum of row credits. Credits are
  `config.credits((tokens_in * price.input + tokens_out * price.output) / 1e6)` from the prices file; nothing is hard-coded.
* Roles seen on B-007: `director` in `intake`, `approaches`, `plan` (one call each); in `run`: `lead` (a milestone review,
  `1 <= calls < number of units`), the plan's `writer` and `verifier`; in `narrate`: `narrator` exactly once. A Story line
  cites the ids of the events it narrates (HR-1).
* A run stopped by the cap has `outcome_class == "stopped_at_cap"`, no `world.completed`, no `artifact.delivered`, and
  `total_credits <= cap`. The Router's budget (PL-03) is the enforcement: nothing over the cap is ever sent. The checks that
  describe a finished run (`terminal_honest`) are not applied to a capped run; the others are.
* A `ReplayMissError` anywhere in the run gives `outcome_class == "replay_miss"` and a `reason` naming the role and the key.
* Estimate: computed before any call, from the case, the role token caps and the prices file; scales linearly with prices.

### CLI (`main`, `evals/scripts/live_e2e.py`, `just live-e2e`)

Flags: `--case ID` (default `B-007`), `--max-credits N`, `--replay`, `--dry-run`, `--bank-dir`, `--models-file`,
`--prices-file`, `--recordings-dir`, `--report-json PATH`. Exit codes: 0 the run ended as the case expects and every hard
check holds (dry run: 0); 1 a hard check failed, the outcome is not the case's, or `replay_miss`/`failed`; 2 refused;
3 `stopped_at_cap`.

stdout, in this order, `key=value` like the Vertex smoke:

```
estimate credits_low=0.0000 credits_high=0.0000 cap=40.0000        # FIRST line, before any model call; a dry run stops here
mode=<live|replay> case=<id>
stage=<stage> role=<role> profile=<profile id> calls=<n> tokens_in=<n> tokens_out=<n> credits=<x.xxxx> latency_ms=<x.x>   # one per row
note: <n> call(s) returned no usage; ...                          # only if a call raised after it may have been billed: its
                                                                    # credits are the pre-call quote, its tokens_out is left out
outcome=<outcome class> events=<n>
check=<GEN-a check name> findings=<n>                               # one per check
total credits=<x.xxxx> cap=<x.xxxx>
```

stderr: refusals are exactly one line `REFUSED <code>: <message>` (exit 2); a stop is exactly one line
`STOP <outcome class>: <message>` (exit 1 or 3). The `stopped_at_cap` message names the cap formatted `%.4f`. A provider's own
error text is never printed or stored (it can echo a credential, PRD 16.1 rule 4).

`--report-json` writes `to_dict()` plus `event_types` (not the full events): keys `case_id, mode, outcome_class, reason,
cap_credits, total_credits, event_count, event_types, rows, checks (check name -> list of finding strings), questions,
answered, estimate, story_lines, side_effects`.

### Codes (`LiveE2ERefused.code`), checked in this order

1. `live_not_enabled`: `LIVE` is not exactly `"1"` (live mode only). Looked at FIRST, before any other key, file or import.
2. `replay_with_live`: `--replay` with `LIVE=1`.
3. `ci_refused`: `CI` or `GITHUB_ACTIONS` non-empty (live mode only). `deployed_refused`: `K_SERVICE` or `CLOUD_RUN_JOB` present, even empty (live mode only).
4. `cap_out_of_range`: `--max-credits` not in `(0, 200]` (every mode).
5. `api_key_present`: `GOOGLE_API_KEY` or `GEMINI_API_KEY` set (names the variable, never the value).
6. `missing_project`: `GOOGLE_CLOUD_PROJECT` unset (live only).
7. `prices_unset`: `config/prices.yaml` `status` is not `set`.
8. `unknown_case`, `config_invalid`: bad `--case` or an unloadable models/prices file.

## Open points left to the builder (see docs/open-questions.md)

* The `safety` role has no live adapter (FR-INT-02 refuses the fake in live mode), so a live run must be given a real
  or recorded safety screen; the tests inject one through `safety=` and leave the default to the builder.
* `prompts/` has no `writer`, `lead` or `narrator` templates yet; the committed fixture must be regenerated with
  `uv run python evals/tests/regen_live_e2e_fixture.py` once the prompts exist.
