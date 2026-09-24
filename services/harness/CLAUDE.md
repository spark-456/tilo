# services/harness — `tilo-harness`

## Purpose
Cloud Run service (PRD 6.2), built on ADK (Python): the single-writer process per world —
planning, agents, handoff, events. Calls the model provider layer for every model interaction.

## Commands
- Package and dev/test commands land with the harness code (ticket P1+).
- `just check` — full gate from the repo root.

## Contracts
- Reads/writes: `packages/contracts-py` event types; Firestore (worlds, events, checkpoints);
  Pub/Sub events to BigQuery.

## Config
- `config/models.yaml`, `config/skills/`, `config/teams/`, `config/autonomy.yaml`.

## Requirement IDs
- FR-P1 through FR-P4 (intake, planning, execution, policy) as pillars land.

## Local rules
- Never calls a model directly — always through `packages/providers`, by role (PL-01).
- Risk tiers assigned from action type and context; a model never decides authorisation.
- No scenario-specific code; a scenario that needs code becomes a pillar requirement first.
