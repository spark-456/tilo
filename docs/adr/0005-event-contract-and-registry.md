# ADR-0005: Event contract, registry and per-type payloads

- Status: Accepted (2026-09-25, architect; ticket P0-03). Freezes with the CP0 set on 29 Sep.
- Deciders: architect, orchestrator
- Requirement: FR-WLD-03 (PRD 9.3 to 9.5, 9.8, 15.2)
- Numbering: ADR-0004 is left to ticket P0-04 (provider layer), in flight at the same time.

## Context
PRD 9.3 fixes the `TiloEvent` fields, 9.4 the honesty rules and 9.5 the event families with a
one-line world effect per family. It does not say how the registry is shaped, which types are
side effects, what each `data` payload holds, what `actor`, `target`, `item.kind` and
`trace.archive_ref` look like, or what the HUD does per type. The renderer's fixture player
(P0-08b) and the harness skeleton (P0-09) need all of it fixed before CP0. Where the PRD is
silent the defaults below apply; each is logged as a BQ in `docs/open-questions.md`.

## Decision
1. **Event shape.** `contracts/event.schema.json` is PRD 9.3 exactly: all twenty fields
   required, `level`, `district`, `item`, `cause` and `authz` nullable, `trace` required with
   its seven fields each nullable (null when no model or tool call happened). `v` is `"1.0"`,
   `seq` an integer from 0, `ts` the common UTC millisecond timestamp, `summary` 1 to 140
   characters, `vis` `"all"` or a non-empty list of district ids. `type` is any lower-case
   `family.verb`, not an enum, so a newer type still parses and HR-5 can show it in the Trace
   only; the harness emits registered types only (EV-01).
2. **Registry.** `contracts/events/registry.yaml` maps each type to `family`, `verb`,
   `priority` (`app.*` could, the rest must), `pillar`, `default_severity`, `side_effect`,
   `authz_by` (side effects only), one `world_effect`, one `hud_effect`, one `story_template`,
   one `trace_row`, `data_schema` and `fixture`; `unknown_types: trace_only` states HR-5 as
   data. Its shape is `events/registry.schema.json`. Templates fill `{actor}`, `{target}` and
   `{data.<required field>}`. World effects follow PRD 9.5 in order; HUD effects follow the
   10.2 notification rungs and the 14.4 meters, with `none` where nothing changes (BQ-24).
3. **Payloads.** One small schema per type in `contracts/events/data/`, closed with
   `additionalProperties: false`. Payloads carry ids and numbers, never message bodies,
   recipients or credentials: channel messages point at the redacted raw-archive record
   (`archive_ref`, `<run id>/<record seq>`), and sends name their outbox entry. Agent handoffs
   carry the typed envelope itself (`envelope.schema.json`, FR-AGT-08). `building.completed`
   carries `unit_type` and `unit_count` (BQ-03); `question.answered` carries `answered_by`
   including `default` (BQ-04).
4. **Side effects and authorisation.** Six types carry `authz` (EV-03, schema):
   `approval.resolved` (a person or Team Lead), `policy.applied` (a policy), `policy.changed`
   and `connection.consented` (a person), `budget.granted` (a person or a policy; spending is a
   T1 side effect) and `data.transfer` (whoever authorised it; a read carries the person's
   connection consent). `event.schema.json` lists the same six; contracts-check fails if the
   lists differ. A policy never authorises T3 (EV-07, schema); `authz.by` is limited per type
   and a policy's `authz.ref` equals the `policy_id` it acted under (EV-04, EV-06). HR-7's link
   is `authz` plus the `gate_id`, `card_id` and `outbox_id` that `approval.requested`,
   `approval.resolved`, `policy.applied` and `data.transfer` share (BQ-23). An outbox entry and
   its outgoing `data.transfer` carry exactly the `authz` of the `approval.resolved` that
   answered `approve` or of the `policy.applied` that opened the gate, never a stamp of their own
   (outbox rule OB-01). `artifact.delivered` is a notice, not a side effect: a format that leaves
   Tilo (email, Google Docs, Sheets or Slides) names its outbox entry and is caused by that
   entry's `data.transfer` out, which carries the `authz` (EV-14). A `vis` list includes the
   event's own district (EV-13, BQ-28).
5. **Ids.** `actor` is a user, agent, Team Lead or policy id, or `system` for the platform
   itself; `target` is a world, level, district, building, plan unit, gate, island, agent,
   artifact, user, Team Lead or policy id (BQ-20). `item.kind` is one of the carried items the
   PRD 9.5 world effects name (BQ-21).
6. **Rules and checks.** Rules the schema cannot express are EV-01 to EV-14 in
   `contracts/event.rules.md`. `just contracts-check` applies them to every event fixture and
   stream; the harness validator applies them before each write. Fixture streams must match a
   layout fixture with the same `world_id` (EV-12).
7. **Generated code.** Python and TypeScript get `Event`, one `<Type>Data` model per type, the
   registry constants, and in TypeScript a `RegisteredEvent` union discriminated on `type`
   (ADR-0002 decision 8).

## Consequences
- Adding an event type means a registry entry, a data schema, a valid fixture and, for a side
  effect, the side-effect list in `event.schema.json`, all in one commit; after CP0 it is a
  minor version of the event contract.
- The renderer maps each registered type to one world effect and one HUD effect and shows any
  other type in the Trace only; the Story lens renders `story_template` or `summary`.
- Builders never hand-write event shapes; they import `tilo_contracts` or `@tilo/contracts`.
- The Village stream fixture (`contracts/fixtures/streams/village-basic.jsonl`) is fixture data
  for P0-08b and P0-09 and is never presented as a replay of a real run.
