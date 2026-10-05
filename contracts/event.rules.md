# Event rules beyond the schema (event.schema.json v1, events/registry.yaml v1)

`event.schema.json` checks one event on its own; `events/data/<type>.schema.json` checks its
`data`. The rules below need the registry, another field or other events. Rules marked "schema"
are already enforced by `event.schema.json`. The harness validator (P0-09) runs every rule
before it writes an event and refuses the event on any failure; `just contracts-check`
(`scripts/contracts_events.py`) runs them over the fixtures and streams below. Rule ids are
stable; a failing check names its rule.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| EV-01 | The harness emits only types listed in `events/registry.yaml`. A consumer that meets a type it does not know (a newer harness, an old replay) shows it in the Trace only: no world animation, no HUD change, no Story line (`unknown_types: trace_only`). | validator; renderer | 9.4 HR-5, 9.5 |
| EV-02 | `data` validates against `events/data/<type>.schema.json`. | validator | 9.3 |
| EV-03 | A side-effect type (`side_effect: true` in the registry) carries `authz`, the `common.schema.json` shape (BQ-01). `event.schema.json` lists the same types; contracts-check fails if the lists differ. | schema | 10.4 Audit, FR-HIL-08 |
| EV-04 | `authz.by` is one of the type's `authz_by`. A gate is resolved by a person or Team Lead (`approval.resolved`; which ones may open it, and the signed-in channel the answer needs, are outbox OB-01's) and opened by a policy only through `policy.applied`; only a person grants a connection (`connection.consented`) or changes a policy (`policy.changed`, PRD 10.1), and that person is the policy's owner: `policy.changed`'s `authz.ref` equals the `owner` of the policy `data.policy_id` names (a Team Lead only proposes; the policy record's stamps are outbox OB-01's). | validator | 10.1, 10.4, HR-7 |
| EV-05 | Only side-effect types carry `authz`; every other event has `authz: null`. The schema accepts `authz` on any type so that a newer side-effect type still parses. | validator | 10.4 |
| EV-06 | When `authz.by` is `policy` and `data` has a `policy_id`, `authz.ref` equals it, so the policy stamp links to the policy that acted. | validator | HR-7 |
| EV-07 | A policy never authorises T3: when `authz.by` is `policy`, `data.risk_tier` (on types that have one) is T1 or T2. | schema | 10.4, FR-HIL-04 |
| EV-08 | An answer applied by default (`answered_by` or `decided_by` is `default`) is posted with severity `nudge` (BQ-04). Gates never time out to go, so no `approval.resolved` is ever applied by default. | validator | 10.3, FR-HIL-02 |
| EV-09 | In `memory.hit`, `saved` equals `origin_cost` minus `lookup_cost`. | validator | 14.3, FR-MTR-06 |
| EV-10 | One writer per world: `seq` strictly increases per world and event ids are unique. A stream fixture holds one world. | validator | 9.3, FR-WLD-04 |
| EV-11 | `cause` is null or the id of an earlier event of the same world. | validator | 9.3, 9.6 |
| EV-12 | `level`, `district`, and an `actor` or `target` that is an agent, level, district, building, gate or island id, exist in the world's layout. | validator | 9.2, 9.5 |
| EV-13 | `vis` is tied to where the event renders: when `district` is set and `vis` lists districts, the list includes `district`, so that district's viewers see what happens in it; every district `vis` lists exists in the world's layout (BQ-28). | validator | 9.3, 10.1, FR-HIL-09 |
| EV-14 | An `artifact.delivered` in a format that leaves Tilo (`email`, `google_docs`, `google_sheets`, `google_slides`) went through the outbox: its `data.outbox_id` names the entry (schema), and its `cause` is that entry's `data.transfer` out with the same `artifact`, which carries the `authz` (validator). A format kept in Tilo has `outbox_id` null (schema). `artifact.delivered` itself is the notice, not the side effect, and carries no `authz`. | schema; validator | 10.4, 12.4, HR-7 |
| EV-15 | Artifact events name versions the world recorded (ADR-0018). An `artifact.created` names version 1 of an `artifact_id` the world has not recorded. An `artifact.reviewed` or `artifact.delivered` names, and an `artifact.versioned` (by `previous_version`) or `artifact.rolled_back` (by `restored_version`) continues, a version that an earlier `artifact.created`, `artifact.versioned` or `artifact.rolled_back` of the same world recorded, same `artifact_id`. A `versioned` or `rolled_back` records the next version (the highest recorded plus 1, AR-02). So no stamp, parcel, version badge or rewind shows for a version never created. (Not PRD 3.5's metric EV-15.) | validator (stream) | 9.4 HR-1, 13.4, FR-MEM-12, FR-CON-15 |

## Registry checks (contracts-check)

- Each entry's `family` and `verb` spell its key; `data_schema` is
  `events/data/<type>.schema.json` and `fixture` is `fixtures/events/valid/<type>.json`, and both
  exist. Every data schema belongs to a registered type.
- `story_template` and `trace_row` use only `{actor}`, `{target}` and `{data.<field>}` for a
  required field of the type's data schema. `{actor}` and `{target}` become display names from
  the layout (the id when there is none). A filled Story line is at most 140 characters, like
  `summary`.
- `side_effect: true` requires `authz_by`; `app.*` is `could` (PRD 9.5).

## Actor, target and payloads

`actor` is who caused the event: a person (`u_`), an agent (`A_`), a Team Lead (`tl_`), a policy
(`pol_`) or `system` (scheduler, sweeper, connector monitor). `target` is what it affected. Each
data schema's description says which is which where it is not obvious; the fixtures show one
example per type. Payloads never carry message bodies, recipients or credentials: channel
messages point at the redacted raw-archive record (`archive_ref`, `<run id>/<record seq>`), and
sends name their outbox entry (`outbox_id`), which holds the recipients and the destination
(`outbox.schema.json`). `approval.requested`, `policy.applied` and an outgoing `data.transfer`
carry the pinned item (artifact id and version) the entry sends, so the Trace shows which
version was approved and sent (outbox rule OB-05). With no gate card on the policy path, `policy.applied` also names
the connector, the destination (an opaque id) and the district the engine checked against the
policy's scope, and the entry equals them (OB-01, OB-05). At L2 it also names the owner's
instruction (`instruction_id`: an earlier `world.requested` the owner made signed in on the web or
mobile web and tilo-api wrote from a typed-instruction control (OB-01 provenance), never one over
email or WhatsApp and never a `channel.message_in` (ADR-0019), with the same `destination`, used by
no other `policy.applied`), which the Trace and HR-7's link show beside
the policy (OB-01).

## Fixtures

- `fixtures/events/valid/<type>.json`: one valid event per registered type (the registry's
  `fixture`); each passes every rule above and round-trips through the generated models.
  `fixtures/events/valid/<type>--<case>.json` is a further valid case of a type, checked the same
  way (`question.answered--from_decision.json` cites the Decision
  `fixtures/decision/valid/owner_answer_all_worlds.json`).
- `fixtures/events/invalid/`: each fails `event.schema.json` or its type's data schema; the file
  name says which rule.
- `fixtures/events/registry/invalid/evNN_*.json`: each passes both schemas and breaks only rule
  EV-NN, the rules only the validator can check.
- `fixtures/streams/village-basic.jsonl`: an ordered Village-tier run of one world, one event
  per line, matching `fixtures/layout/valid/village_basic.json` (EV-10 to EV-14). It is the
  renderer fixture player's (P0-08b) and the harness skeleton's (P0-09) input. It is fixture
  data, never shown as a replay of a real run.
- `fixtures/streams/artifact-versions.jsonl`: a short stream of the same world in which an
  artifact is created, versioned, restored, reviewed and delivered (EV-15).
- `fixtures/streams/invalid/evNN_*.jsonl`: each event passes both schemas and the stream breaks
  only rule EV-NN.
