# evals — `tilo_evals`

## Purpose
The eval harness (PRD 19, EFF-06, EFF-07). P8-06a/b: case schema/loader, `EvalsConfig`, the check registry with its seven deterministic checks (the five of PRD 19.3 plus the E-ROUTE pair `routed_domain` and `answered_from_decision`). P8-06c/d: `ReplayExecutor`, `run_pass` with the credit cap (MT-09), `evals/results.md` and the CLI. Issue #272 (GEN-01..): the generality bank, apart from the 160 cases.

## Commands
- `just eval` — replay every case under `evals/cases/` (full pass) into the git-ignored `evals/results.local.md`; `uv run python -m tilo_evals run --pass smoke|full|gate [--group G] [--case ID] [--results-md P] [--results-json P]`
- `uv run python -m tilo_evals bank [--case B-007] [--repeat 3]` — the generality bank (`evals/bank/B-NNN.yaml`, own `bank.schema.json`) end to end on fakes into git-ignored `evals/bank-results.local.md`; exit 0 all hard checks pass, 1 any fails, 2 refused (LIVE, K_SERVICE or CLOUD_RUN_JOB set) or bad bank
- `just live-e2e [--case B-007] [--dry-run|--replay]` (PL-LIVE-E2E, `live_e2e.py`, `docs/live-e2e.md`) — one bank case through the real pipeline on the real profiles; live only with the user's `LIVE=1` (never CI or Cloud Run), ADC only, capped (default 40, max 200 credits), `TILO_RECORD=1` records to `evals/bank/live/<case>/model-recordings/`; `--replay` is free and runs in CI
- `uv run pytest "evals/tests" -q` — the tests (fake repos under `tmp_path`, never `evals/cases`)
- Exit codes: 0 every case that ran passed (or none ran), 1 a case failed, 2 the pass could not run (bad config or case file, unknown `--case` or `--group`, `--live` refused), 3 stopped at the credit cap with no failure.

## Contracts
- Reads `evals/case.schema.json` (local; issue #8) for every `evals/cases/<group>/<id>.yaml`. A case's `recording` is a JSONL file of TiloEvents (path relative to the repo root) with an optional final `{"outputs": {...}, "credits": n}` line; the case costs the larger of the summary credits and the sum of the event credits.

## Config
- `config/evals.yaml` via `EvalsConfig.load`: `credit_cap` per pass kind, `deploy_gate_repeats`; tests pass a `tmp_path` path.

## Generality bank (#272)
- Runs the real `tilo-api` in process (intake to delivery); only the Director is scripted per case (`scripted.py`, through the provider layer's Router), the unit runner and connectors are the dev stand-ins. It tests the pipeline's mechanics across plan shapes, never model judgement, and its report says so (GEN-11).
- Frozen and held out: `evals/bank/MANIFEST.sha256` pins the set; a change needs the user's approval. A failing case is fixed in code in general, never by naming its brief anywhere outside `evals/bank/`.
- Hard checks (GEN-03): no crash, events valid, plan valid, gates as policy, honest terminal state, budget. `delivers_something` is reported, not gated (items made but none delivered; the plan's `deliver` unit delivers them, BQ-218).

## Requirement IDs
- EFF-07 (a to d); GEN-01 to GEN-05, GEN-11 (bank, issue #272). Supports EFF-06 (nightly cost regression, later) and the PRD 19.2 case set.

## Local rules
- No paid calls: only `ReplayExecutor` exists. `--live` refuses without the user's `LIVE=1` and, with it, says no live executor is built (it would go through `packages/providers`). No model id here (PL-01): results show profile names from each event's own trace.
- A full pass runs every case once and deploy-gate cases `deploy_gate_repeats` times (PRD 19.2); every run counts against the cap, and counts are then labelled runs.
- Credit cap (MT-09): a case that would take the spend over `credit_cap[pass]`, and every case after it, is listed as not run with a stop reason; a pass whose cap is reached starts nothing more. Bad recordings (unreadable; credits negative, NaN, huge, a bool or a string) make a case not runnable, with the reason recorded, and never crash the pass.
- Autorater checks (`kind: autorater`) are never run here: reported as pending, never counted as passed.
- `evals/results.md` is the official file (PRD 19.5): the CLI default, committed deliberately on pass dates (7, 12, 15 Oct); `just eval` writes `evals/results.local.md` instead so dev runs never dirty the tree. It keeps the latest run of each pass kind (counts first, per case group, spread, failures by cause, not runnable, not run).
- `load_cases` rejects an unregistered check (a `kind: autorater` check is skipped, not looked up). A check is `get(name)(case, outcome, args)`; `args` is that entry's `checks[i].args`.
- Case YAML is parsed with a no-alias loader: any `&anchor`/`*alias` in a case file is rejected, never expanded.
- A check never passes on a missing or mistyped field: `schema_valid` and `recipients_within` fail with "field missing"; `recipients_within` needs a list of strings; `schema_valid` refuses a `schema` path outside `contracts/` and fails (never skips) on an unreadable contract schema; `equals_ground_truth` is bool-vs-number strict at every depth; `register` accepts only `deterministic` or `autorater`. `flagged_or_blocked` still accepts any `alert.raised` (open question BQ-108: needs a contract marker).
