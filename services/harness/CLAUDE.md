# services/harness — `tilo-harness`

## Purpose
Cloud Run service (PRD 6.2), built on ADK (Python): the single-writer process per world —
planning, agents, handoff, events. Calls the model provider layer for every model interaction.

## Commands
- `uv run pytest services/harness/tests -m "not emulator"` — fast suite
- `uv run pytest services/harness/tests -m emulator` — Firestore-emulator suite (Java + firebase-tools)
- `just harness-skeleton` — runs `python -m tilo_harness.skeleton` against the emulator; `just check` — full gate. Image: `services/harness/Dockerfile` runs `tilo_harness.app:app` (`/healthz` only, P0-07a).

## Contracts
- Reads (read-only): `contracts/event*`, `common`, `events/{registry.yaml,data/*}`, `layout`, `plan`,
  `envelope`, `skill`, `agents`, `manifest` schemas. `EventValidator` is a fresh EV-01..EV-15 implementation
  (never imports `scripts/`); `contract_problems(name, x)` checks any other contract.
- Writes: Firestore (worlds, events, views, checkpoints); Pub/Sub to BigQuery (later ticket). Own fixtures: `fixtures/three_agent/`, `tests/fixtures/skills*/`.

## Config
- `config/agents.yaml` via `config.load_agents_config()` (invalid or missing: `AgentsConfigError`, start-up stops).

## Requirement IDs
- P0-09 (D-11): skeleton, writer, store. FR-AGT-01/02/03: `executor.run_plan` (PG-02/03/11
  pre-flight writes nothing; `max_specialists` semaphore; deps before start), skill pins. `run_plan(artifacts=, scope=, archive=, redact=)`: `outputs.keep` stores `UnitOutcome.outputs` + `created` manifest, then `artifact.created`/`versioned` from the record (ADR-0018 T3; no store + outputs fails the unit).
- FR-AGT-05: `must_ask.MustAsk` (rules in code; a model reply can only add a question; card stored first);
  `run_plan(must_ask=)` parks the asked unit. FR-HIL-10: `question_wait=` (`QuestionWait`) waits (no slot; a failed answer never strands the deadline, #338) and `Ask.runs` decides: Hold/default leave it held.
- FR-AGT-12: `verifier.Verifier` (rules in code, then only the verifier-role model; `verified` recomputed); `run_plan(verifier=)` reviews every handed-over artifact.

## Local rules
- Never calls a model directly — always through `packages/providers`, by role (PL-01); the
  default `UnitRunner` gets providers keyed by role name. Prompts live in `prompts/<role>/`.
- `WorldWriter` is the only writer per world: every event is checked against `EventValidator`
  first; a rejected event writes nothing. A lease on `orgs/{org}/worlds/{world}/_head/state`
  enforces one writer, re-checked inside the same store transaction on every write; Firestore
  contention (ABORTED) surfaces as `WriterBusy`. An identical resend to `append` returns the committed event and writes nothing (FR-HIL-07); any other id reuse is EV-10.
- A run loads skills only from its pins; a changed skill file fails that unit closed.
- `FirestoreStore` refuses to start without `FIRESTORE_EMULATOR_HOST` and a `demo-` project id (ADR-0003: emulator only, no cloud credentials, never a real project).
- `@pytest.mark.emulator` tests are excluded from `just check`'s default run (own CI step; `-m emulator`).
- No scenario-specific code; a scenario that needs code becomes a pillar requirement first.
- `_head/**` must deny every client once a rules file exists: it holds every scope's view_seq
  (PRD 10.1/SEC-07). Risk tiers come from action type; a model never decides authorisation.
