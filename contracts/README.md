# contracts

Versioned JSON Schemas (draft 2020-12) for every structure that crosses a service boundary
(PRD 15.2). They are the first source of truth: where the PRD prose and a contract disagree,
the contract wins. Conventions are in [ADR-0002](../docs/adr/0002-contract-conventions.md).

| File | Describes | Version |
| --- | --- | --- |
| `common.schema.json` | Shared definitions: ids, ULID, timestamps, credits, severity, risk tier, autonomy level, `authz`, artifact refs, tier, artifact media types, the people ids (`wi_`, `mt_`, `pb_`, `mn_`, `ce_`, `tm_`, utterance), `opaque_ref`, `maker`, `record_ref`; 1.2.0 merges the artifact media types (1.1.0, ADR-0018) and the people ids (1.1.0, ADR-0016); both 1.1.0 releases carried different content, so 1.2.0 is the first version that has both (additive, no breaking change); 1.3.0 adds `mail` to `record_ref.kind` (ADR-0021) | 1.3.0 |
| `brief.schema.json` | Structured brief from intake (FR-INT-03 to 05) | 1.0.0 |
| `plan.schema.json` | `PlanGraph`: approaches, units, dependencies, gates, budget cap; rules in `plan.rules.md` | 1.0.0 |
| `layout.schema.json` | `WorldLayout` v1: semantic part and solver geometry; rules in `layout.rules.md` | 1.0.0 |
| `event.schema.json` | `TiloEvent` v1; rules EV-01 to EV-16 in `event.rules.md`; 1.1.0 adds the optional `trace.tokens_cached` (EFF-04, ADR-0022) | 1.1.0 |
| `events/registry.yaml` + `events/registry.schema.json` | Every registered event type (PRD 9.5, plus the CC-PEOPLE families `work_item`, `pinboard`, `mention`, `calendar`, `assistant` and `meeting.minuted`): world, HUD, Story and Trace effects, data schema, fixture, pillar | 1.1.0 |
| `events/data/<type>.schema.json` | The `data` payload of each registered type (82 files); `question.answered` is 1.1.0 (`decision_id`), `budget.requested` is 1.1.0 (`remaining_units`, `estimate`), `artifact.created` is 1.1.0 (`content_sha256`, `media_type`, `size_bytes`); `meeting.started` and `meeting.ended` are 1.1.0 (optional `meeting_id`, `reason`); the 12 CC-PEOPLE types are 1.0.0 | 1.0.0 |
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
| `artifact.schema.json` | `ArtifactVersion`: one stored artifact version and its manifest revisions (ADR-0018, FR-MEM-12); rules AR-01 to AR-08 in `artifact.rules.md` | 1.0.0 |
| `metering.schema.json` | `config/metering.yaml`: reserve margin, budget-request threshold, credit caps, daily spend caps, reconciliation; rules for this and the next four in `metering.rules.md` | 1.0.0 |
| `meter.schema.json` | The HUD meter's state for one run: credits used and saved, time saved with range and method link, budget | 1.0.0 |
| `attention.schema.json` | One measured span of a person's steering or review time, subtracted from time saved | 1.0.0 |
| `evals.schema.json` | `config/evals.yaml`: eval pass credit caps, deploy-gate repeats, cost-regression threshold, case counts per group | 1.0.0 |
| `pilot.schema.json` | EV-G3 pilot records by pseudonymous tester id: consent, run and card tags, diary entries, survey responses | 1.0.0 |
| `person.schema.json` | A person of an org: aliases, time zone, preferred channel, team memberships assigned by an org owner (ADR-0015); rules PE-01 to PE-30 in `people.rules.md` | 1.0.0 |
| `meeting.schema.json` | A meeting Tilo attended or took a transcript of: owner, agenda, attendees as said, attestation, retention; no field for a join link; 1.1.0 adds an optional `world_id` (ADR-0020); 1.2.0 refuses more link forms and hidden characters in the title, agenda titles and attendee names (PE-13, ADR-0016 decision 14) | 1.2.0 |
| `minutes.schema.json` | The structured minutes of one meeting: summary, decisions, action items, agenda coverage, every item citing utterance ids | 1.0.0 |
| `work_item.schema.json` | One thing a person has to do; proposed until the meeting Owner confirms an item Tilo made | 1.0.0 |
| `pinboard_item.schema.json` | An entry on a personal or team pinboard; Tilo's entries carry a source and, on the team board, a confirmation | 1.0.0 |
| `mention.schema.json` | An @mention of a team member on a team entry | 1.0.0 |
| `calendar_entry.schema.json` | A stored calendar entry (cached Google event, own or proposed), plus the `agenda_item` read-model row and `free_busy` | 1.0.0 |
| `ui_action.schema.json` | The assistant panel's closed allow-list of UI actions (FR-PA-14) | 1.0.0 |
| `transcript.schema.json` | The content of a transcript artifact version (utterances), plus the `evidence_quote` read-model row tilo-api cuts per request (ADR-0020, PE-22 to PE-25) | 1.0.0 |
| `plate.schema.json` | A person's plate (FR-PA-02): the read model S-27, the digest and the panel share; rows and parked lanes, groups and order by code (ADR-0021, PE-26 to PE-30) | 1.0.0 |
| `scenario.schema.json` | `config/scenarios/<id>.yaml` (FR-INT-11, ADR-0014): skills, connectors, seed data, theme and autonomy policy seeds, and nothing else; rules SN-01 to SN-09 in `scenario.rules.md` | 1.0.0 |

Still to come: `appspec` (Could).

- `fixtures/<name>/valid|invalid/*.json` exercise each schema root; `fixtures/<name>.<def>/`
  exercise one `$defs` entry. Invalid file names say which rule they break.
  `fixtures/card/crossref/` holds cross-reference cases for the card validator (CR-09 to CR-12);
  `fixtures/transcript/crossref/` and `fixtures/plate/crossref/` hold the quote and plate cases (PE-19, PE-22 to PE-27).
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
