# evals — `tilo_evals`

## Purpose
The eval harness (PRD 19, EFF-06, EFF-07). Parts a+b of P8-06: case schema/loader, `EvalsConfig`, and the check registry with its five deterministic checks. Executors/runner and the credit cap (c), `evals/results.md` (d) come later.

## Commands
- `uv run pytest "evals/tests" -q` — `just eval` not wired up yet (part c adds the runner)

## Contracts
- Reads `evals/case.schema.json` (local; issue #8) for every `evals/cases/<group>/<id>.yaml`.

## Config
- `config/evals.yaml` (local stub, issue #8) via `EvalsConfig.load`; tests pass a `tmp_path` path.

## Requirement IDs
- EFF-07 (part a). Supports EFF-06 and the PRD 19.2 case set (later tickets).

## Local rules
- No paid calls: this part has no executor yet.
- `load_cases` rejects an unregistered check (a `kind: autorater` check is skipped, not looked up); `checks.register`/`is_registered` are the only entry points until part b (which adds lookup). Fake cases live under `tmp_path`, never `evals/cases`.
- Case YAML is parsed with a no-alias loader: any `&anchor`/`*alias` in a case file is rejected, never expanded.
