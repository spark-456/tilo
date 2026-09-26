# packages/planning — `tilo_planning`

## Purpose
Pillar P1 intake and planning (PRD 7). FR-INT-01/02: `intake.submit_intake` enforces the limits,
types and extracts files (`extraction`), screens them with a `SafetyProvider` and stores them as
versioned artifacts with an origin record (`artifacts`). FR-INT-03/04/05: `brief.extract_brief` asks
the `director` role (through `tilo_providers.router.Router`) for a brief and the ambiguous fields;
`questions.generate_questions` checks `memory` first, then ranks and caps the questions in code.
FR-INT-09: `plangraph.validate_plan` checks a plan against `plan.schema.json` and PG-01..PG-11
(`plan.rules.md`) with no model, returning every `Violation` with its rule id.

## Commands
- `uv run pytest packages/planning` — tests; `just check` — full gate from the repo root

## Contracts
- Builds `world.requested`, `artifact.created`, `memory.hit` and `plan.questions_asked` events
  (`events.build_event`, validated with `tilo_contracts`); returns them, never writes them (the
  harness is the writer). Briefs are validated with the generated `Brief` (`brief.schema.json`).

## Local rules
- Model calls only through the router with a role from `config/models.yaml`; prompt text only in
  `prompts/director/`; task text goes in as delimited data (PRD 16.3 item 1). Intake and extraction
  make no model calls; extraction is stdlib only and treats uploads as untrusted (bounded
  decompression, no DTDs in XML).
- The model only flags ambiguous fields. Memory lookup, ranking, the cap of 3 and assumptions are
  code; a candidate over the cap is recorded as an assumption with `question: null`.
- A rejected submission stores nothing: limits first, then extraction and screening, then storage.
- The plan validator takes its registries (risk table, connectors, skills, policies) as arguments;
  a schema failure (`schema`) stops the PG checks. PG-06 checks "never lower" only.
- A flagged file's `artifact.created` has severity `fyi` and `trace.tool` `safety_provider`;
  `trace.archive_ref` stays null until the raw archive (P7) exists.
