# packages/planning — `tilo_planning`

## Purpose
Pillar P1 intake and planning (PRD 7). FR-INT-01/02: `intake.submit_intake` enforces the limits,
types and extracts files (`extraction`), screens them with a `SafetyProvider` and stores them as
versioned artifacts with an origin record (`artifacts`). FR-INT-03/04/05: `brief.extract_brief` asks
the `director` role (through `tilo_providers.router.Router`) for a brief and the ambiguous fields;
`questions.generate_questions` checks `memory` first, then ranks and caps the questions in code.
FR-INT-09: `plangraph.validate_plan` (plan schema, PG-01..PG-11, no model); `compiler.compile_plan`: the `director`
drafts units, code adds gates, cap and a final `deliver` unit (BQ-218), one repair sends rule ids and pointers in data blocks (BQ-115).
FR-INT-06/07/08: `approaches.propose_approaches` asks the `director` role for 2-3 approaches and checks
PG-07/08/09 in code (one repair through the router, then reject); `estimate.estimate_units` sums
historical unit costs (seed table `unit_cost_seed.json`, empty at launch, PRD 7.3); `budget` grants a
budget by the person or, via `tilo_policy.decide`, by an L3 policy on the `grant_budget` action type.
FR-INT-12: `refusal` (`config/out_of_policy.yaml`). Tests: `uv run pytest packages/planning`; `just check` is the gate.

## Contracts
- Builds `world.requested`, `artifact.created`, `memory.hit`, `plan.questions_asked`, `plan.approaches_proposed`
  and `budget.granted` events (`events.build_event`, validated with `tilo_contracts`); returns them, never
  writes them (the harness is the writer). Briefs are validated with the generated `Brief` (`brief.schema.json`).

## Local rules
- Model calls only through the router with a role from `config/models.yaml`; prompt text only in
  `prompts/director/`; task text goes in as delimited data (PRD 16.3 item 1). Intake and extraction make no
  model calls; extraction is stdlib only and treats uploads as untrusted (bounded decompression, no DTDs).
- The model only flags ambiguous fields. Memory lookup, ranking, the cap of 3 and assumptions are code; a
  candidate over the cap is an assumption with `question: null`. A rejected submission stores nothing.
- The plan validator takes its registries as arguments; a `schema` failure stops the PG checks. A plan deeper than
  `MAX_PLAN_DEPTH` (no recursion) or over `MAX_PLAN_BYTES` (BQ-107) is `schema` before any other walk; the schema
  has every `$ref` inlined, a linear `uniqueItems` (`schema_guard`, #173), stops at `MAX_ERRORS` and caps messages;
  non-finite numbers are `schema`. The first caller with client JSON (FR-INT-10) must pass `owner` (BQ-72) and run
  it off the event loop. PG-06 checks "never lower" only, against the higher of the table and connector tiers.
- A flagged file's `artifact.created` has severity `fyi` and `trace.tool` `safety_provider`; `trace.archive_ref`
  stays null until the raw archive (P7) exists. Estimates are arithmetic only; an unknown unit type refuses.
- A budget grant's authz comes only from the owner (PRD 10.1) or the policy engine; the risk table is a parameter and
  an unlisted `grant_budget` fails closed (every grant waits). A policy grant is one `budget.granted` (authz by
  policy, no gate, no `policy.applied`); its daily limits count earlier policy grants.
- Refusal (FR-INT-12): the Director only names a category (`out_of_policy`, null or absent = in policy); code raises
  `TaskRefused` with the configured reason and alternative, so no model or task text reaches a person. An unknown
  or non-string category is `BriefExtractionError` (fail closed); a bad config is `RefusalConfigError`.
