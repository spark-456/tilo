# packages/world — `tilo_world`

## Purpose
The deterministic layout solver (PRD 9.1, FR-WLD-01, CL-INT-6): `solve(semantic, solver_version, edges)` returns
`geometry` for `contracts/layout.schema.json`. The layout validator (WE-01..WE-14) will live here too.

## Commands
- `uv run pytest packages/world -q` — tests; `just check` — full gate from the repo root

## Contracts and config
- Reads nothing at run time; its output is checked against `contracts/layout.schema.json` and
  `contracts/layout.rules.md` (tests, and `tilo_api.layout` before it stores a layout). Writes no events. No config.

## Requirement IDs
- FR-WLD-01 (solver half), WE-06 (roads), WE-09 (tints `district.1`..`district.6`), WE-11 (replay determinism).

## Local rules
- Pure and standard library only: no randomness, clock, I/O, model call or import of another Tilo package.
- Order is the semantic order; never sort by hash or dict order. `edges` are plan dependencies (dependency unit,
  dependant unit) because `semantic` carries none; roads are one per building pair, sorted by building order.
- A change to placement needs a new `SOLVER_VERSION`; an input it cannot place raises `SolverError`, never a guess.
