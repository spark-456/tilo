# contracts

Versioned JSON Schemas (draft 2020-12) for every structure that crosses a service boundary
(PRD 15.2). They are the first source of truth: where the PRD prose and a contract disagree,
the contract wins. Conventions are in [ADR-0002](../docs/adr/0002-contract-conventions.md).

| File | Describes | Version |
| --- | --- | --- |
| `common.schema.json` | Shared definitions: ids, ULID, timestamps, credits, severity, risk tier, autonomy level, `authz`, artifact refs, tier | 1.0.0 |
| `brief.schema.json` | Structured brief from intake (FR-INT-03 to 05) | 1.0.0 |
| `plan.schema.json` | `PlanGraph`: approaches, units, dependencies, gates, budget cap; rules in `plan.rules.md` | 1.0.0 |
| `layout.schema.json` | `WorldLayout` v1: semantic part and solver geometry; rules in `layout.rules.md` | 1.0.0 |
| `event.schema.json` | `TiloEvent` v1; rules EV-01 to EV-14 in `event.rules.md` | 1.0.0 |
| `events/registry.yaml` + `events/registry.schema.json` | Every registered event type (PRD 9.5): world, HUD, Story and Trace effects, data schema, fixture, pillar | 1.0.0 |
| `events/data/<type>.schema.json` | The `data` payload of each registered type (70 files); `question.answered` is 1.1.0 (`decision_id`) | 1.0.0 |
| `outbox.schema.json` | An authorised side effect waiting to run exactly once; rules in `outbox.rules.md` | 1.0.0 |
| `card.schema.json` | Needs-you, gate, consent and meeting cards; safe-default rules in `card.rules.md` | 1.0.0 |
| `policy.schema.json` | Autonomy policies and the risk-tier table shape (`config/autonomy.yaml`) | 1.0.0 |
| `team_lead.schema.json` | A Team Lead's owner-assigned domain (`config/teams.yaml` entries); who may open a gate is outbox OB-01 | 1.0.0 |
| `handoff.schema.json` | Context handoff note | 1.0.0 |
| `envelope.schema.json` | Agent-to-agent handoff envelope | 1.0.0 |
| `skill.schema.json` | `skill.yaml` | 1.0.0 |
| `connector.schema.json` | Connector declarations | 1.0.0 |
| `providers.schema.json` | `config/models.yaml` and `config/prices.yaml` | 1.0.0 |
| `agents.schema.json` | `AgentsConfig`: `config/agents.yaml`, the harness's role limits, context thresholds, liveness, retries and question cap | 1.0.0 |
| `decision.schema.json` | An answer kept to answer repeat questions (`orgs/{org}/decisions`); rules in `decision.rules.md` | 1.0.0 |
| `manifest.schema.json` | Provenance manifest of an artifact version (frozen 1 Oct); rules in `manifest.rules.md` | 1.0.0 |

Still to come: `scenario` (1 Oct), `appspec` (Could).

- `fixtures/<name>/valid|invalid/*.json` exercise each schema root; `fixtures/<name>.<def>/`
  exercise one `$defs` entry. Invalid file names say which rule they break.
  `fixtures/card/crossref/` holds cross-reference cases for the card validator (CR-09 to CR-12).
- `fixtures/events/` holds one valid event per registered type, invalid events, and
  `registry/invalid/` cases that only the registry rules catch; `fixtures/streams/*.jsonl` are
  ordered event streams that match a layout fixture (see `event.rules.md`).
- `just contracts-gen` regenerates the Python (`packages/contracts-py`, `tilo_contracts`) and
  TypeScript (`packages/contracts-ts`, `@tilo/contracts`) types, plus the registry constants
  (`EVENT_TYPES`, `SIDE_EFFECT_EVENT_TYPES`, `EVENT_REGISTRY`, per-type data models, and in
  TypeScript the `RegisteredEvent` union discriminated on `type`).
- `just contracts-check` validates schemas and fixtures and fails on any drift; `just check`
  runs it first.
- Generated types check shapes only. Conditional rules (`if`/`then`, `contains`) are enforced
  by validating against the schema, and cross-reference rules by the validators that
  `*.rules.md` describe.
