# evals — `tilo_evals`

## Purpose
The eval harness (PRD 19, EFF-06, EFF-07): a case schema and loader (`evals/case.schema.json`,
`evals/cases/<group>/<id>.yaml`), a registry of deterministic checks, replay/fake executors, a
pass runner (`smoke` | `full` | `gate`) that stops at a per-pass credit cap, and honest results
reporting to `evals/results.md`.

## Commands
- `uv run pytest "evals/tests" -q` — this package's tests
- `uv run python -m tilo_evals run --pass smoke|full|gate [--group G] [--case ID]... [--results-md PATH] [--results-json PATH] [--live]`
- `just eval` — `uv run python -m tilo_evals run --pass smoke` (replay only, so CI stays free)
- `just check` — full gate from the repo root

## Contracts
- Reads: `evals/case.schema.json` (local; contract-change issue #8) for every case; `tilo_contracts.SIDE_EFFECT_EVENT_TYPES`
  for the `no_side_effects` check.
- Writes: `evals/results.md` (appends a dated section per run) and, when `--results-json` is
  given, a JSON report with cost per case and per role (consumed by the nightly cost-regression
  ticket, EFF-06).

## Config
- `config/evals.yaml` (local stub for contract-change issue #8), loaded by `tilo_evals.EvalsConfig.load`.
- `config/models.yaml` is never read here: the results reporter takes role -> profile pairs
  straight from each event's own `trace.model_role` / `trace.profile` fields (PL-01: a model id
  never appears in `evals/results.md`).

## Requirement IDs
- EFF-07 (this ticket). Supports EFF-06 (nightly cost regression, a later ticket) and the PRD
  19.2 case set (170 case skeletons, a later ticket).

## Local rules
- No paid calls in dev or CI: `ReplayExecutor` only replays recordings; `--live` refuses without
  `LIVE=1` in the environment, and even with it says the live executor is not built yet (it needs
  `packages/providers`).
- Deterministic checks run before any autorater; an autorater check is never run in replay and
  never counts as a pass (P8-06 ticket spec).
- `evals/results.md` never prints a model id (PL-01) -- only profile names, taken from trace
  fields already on the event, never resolved through `config/models.yaml`.
- Fake cases and recordings for tests live under `tmp_path`, never under `evals/cases` or
  `evals/recordings` (kept empty until the 170-case ticket).
