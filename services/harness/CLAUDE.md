# services/harness — `tilo-harness`

## Purpose
Cloud Run service (PRD 6.2), built on ADK (Python): the single-writer process per world —
planning, agents, handoff, events. Calls the model provider layer for every model interaction.

## Commands
- `uv run pytest services/harness/tests -m "not emulator"` — fast suite
- `uv run pytest services/harness/tests -m emulator` — Firestore-emulator suite (Java + firebase-tools)
- `just harness-skeleton` — runs `python -m tilo_harness.skeleton` against the emulator
- `just check` — full gate from the repo root

## Contracts
- Reads (read-only): `contracts/event*.{schema.json,rules.md}`, `contracts/common.schema.json`,
  `contracts/events/{registry.yaml,data/*.schema.json}`, `contracts/layout.schema.json`,
  `contracts/plan.schema.json`, `contracts/envelope.schema.json`. `EventValidator` is a fresh
  implementation of EV-01..EV-14 (never imports `scripts/`), checked against every fixture.
- Writes: Firestore (worlds, events, views, checkpoints); Pub/Sub to BigQuery (later ticket).
- Own fixtures: `fixtures/three_agent/{layout,plan}.json`, validated against `plan.schema.json`
  and `layout.schema.json`.

## Config
- `config/models.yaml`, `config/skills/`, `config/teams/`, `config/autonomy.yaml`.

## Requirement IDs
- FR-P1..FR-P4 as pillars land. P0-09 (FR-AGT-01 partial, D-11, PRD 15.3): harness skeleton.

## Local rules
- Never calls a model directly — always through `packages/providers`, by role (PL-01); the
  P0-09 fixture plan makes zero model calls (deterministic ADK `BaseAgent`s, no `LlmAgent`).
- Risk tiers from action type and context; a model never decides authorisation.
- `WorldWriter` is the only writer per world: every event is checked against `EventValidator`
  first; a rejected event writes nothing. A lease on `orgs/{org}/worlds/{world}` enforces one
  writer, re-checked inside the same store transaction on every write.
- `FirestoreStore` refuses to start without `FIRESTORE_EMULATOR_HOST` and a `demo-` project id
  (ADR-0003: emulator only, no cloud credentials, never a real project).
- `@pytest.mark.emulator` tests are excluded from `just check`'s default run; they run as their
  own CI step and via `uv run pytest services/harness/tests -m emulator`.
- No scenario-specific code; a scenario that needs code becomes a pillar requirement first.
