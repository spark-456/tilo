# packages/policy — `tilo_policy`

## Purpose
The deterministic policy engine (PRD 10.4): risk tiers, the covering policy, and the decision
`gate` / `draft_only` / `run_after_undo` / `run`; opening a gate on a person's or allowed Team
Lead's approve; checking an outbox entry against what was authorised (OB-01, OB-05).

## Commands
- `uv run pytest packages/policy/tests -q` (public API pinned in `tests/API.md`); `just check`

## Contracts
- Reads `contracts/policy.schema.json` (`$defs.risk_tier_table`), policy records, approval and
  `policy.applied` event parts, `contracts/fixtures/outbox/crossref/`. Rules:
  `contracts/outbox.rules.md`, `docs/security/p4-policy-invariants.md`. Writes nothing.

## Config
- `config/autonomy.yaml` is `load_risk_table()`'s default; not in the repo yet
  (spark-456/tilo#1), so callers pass an explicit path.

## Requirement IDs
- FR-HIL-03, FR-HIL-04, FR-HIL-05, FR-HIL-08, engine half of FR-HIL-06; PI-01..PI-16 (P4-01).

## Local rules
- No model, provider, network, randomness or clock read under `src/` (AST test). `now` and
  event `at`/`ts` fields are the only time sources.
- Every input is validated against `contracts/*.schema.json` (`schemas.py`) before use: a
  policy that fails covers nothing, an event part or entry that fails opens nothing, and
  `check_entry` returns "OB-01". Facts of the wrong type are T3. Timestamps are ASCII digits.
- Fail closed: unknown action type is T3; any exception gates. Only `open_gate` with a human
  approve opens a gate.
- `applied` must hold the owner's `policy.applied` parts across every world (each with its
  `credits`), not just this world's, or a daily cap multiplies by the number of worlds.
- `decide` is live: a policy with any stamp dated after `now` covers nothing, and duplicate ids
  among the given policies gate. Reading a policy back to an earlier level is `check_entry`'s only.
- `coverage.py` is the one copy of the coverage, stamping and answerer predicates.
- A tier's `max_level` caps a covering policy's level. An L2 cap hit reuses the `l3_*_cap_reached`
  reason codes (API.md has no L2 cap code).
