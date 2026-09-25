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
| `card.schema.json` | Needs-you, gate, consent and meeting cards; safe-default rules in `card.rules.md` | 1.0.0 |
| `policy.schema.json` | Autonomy policies and the risk-tier table shape | 1.0.0 |
| `handoff.schema.json` | Context handoff note | 1.0.0 |
| `envelope.schema.json` | Agent-to-agent handoff envelope | 1.0.0 |
| `skill.schema.json` | `skill.yaml` | 1.0.0 |
| `connector.schema.json` | Connector declarations | 1.0.0 |
| `providers.schema.json` | `config/models.yaml` and `config/prices.yaml` | 1.0.0 |

Still to come: `event.schema.json` and `events/` (ticket P0-03), `manifest` and `scenario`
(1 Oct), `appspec` (Could).

- `fixtures/<name>/valid|invalid/*.json` exercise each schema root; `fixtures/<name>.<def>/`
  exercise one `$defs` entry. Invalid file names say which rule they break.
  `fixtures/card/crossref/` holds cross-reference cases for the card validator (CR-09 to CR-12).
- `just contracts-gen` regenerates the Python (`packages/contracts-py`, `tilo_contracts`) and
  TypeScript (`packages/contracts-ts`, `@tilo/contracts`) types.
- `just contracts-check` validates schemas and fixtures and fails on any drift; `just check`
  runs it first.
- Generated types check shapes only. Conditional rules (`if`/`then`, `contains`) are enforced
  by validating against the schema, and cross-reference rules by the validators that
  `*.rules.md` describe.
