# Decision rules beyond the schema (decision.schema.json v1)

PRD 8.3 and 13.1: a person's or Team Lead's answer becomes a Decision, and a later question
like it is answered from the Decision with a citation (FR-AGT-07). A reused answer reaches
nobody, so these rules keep it inside the authority, scope and time of the original answer.
`decision.schema.json` checks one document; `tilo-api` checks DC-01 to DC-03 before it writes a
Decision, and the harness checks DC-04 before it emits `question.answered` with
`answered_by: decision` (P7 validator tests cover them). Rule ids are stable.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| DC-01 | A Decision records the answer to `source.card_id`, a card of `source.world_id` and `source.run_id` in the org `org_id`. `answered_by` is who gave that answer (the `question.answered` actor, or the `authz` of `approval.resolved`) and `answered_by.at` is when. An answer applied by default or taken from a Decision makes no new Decision. `answered_by.by` is `person` or `team_lead`, never a policy or a model (schema). | validator (schema for `by`) | 8.3, 13.2, FR-MEM-08 |
| DC-02 | A Team Lead's Decision: `answered_by.ref` names a `team_lead.schema.json` record whose `domain` equals the Decision's `domain` (never null, schema) and which the world's owner assigned no later than `answered_by.at`, as outbox OB-01 requires for a Team Lead's answer. | validator (schema for non-null `domain`) | 8.3, 10.1, 16.2 |
| DC-03 | `created_at` is no earlier than `answered_by.at`; `expires_at`, when set, is later than `created_at`. | validator | 13.1 |
| DC-04 | `question.answered` with `answered_by: decision` cites in `data.decision_id` (schema) a Decision of the world's org that was created before the event's `ts`, has not expired at `ts`, and whose `scope` covers the event's world and district. A Team Lead's Decision answers only questions routed with its `domain` (`question.routed` `data.domain`); an owner's Decision answers any domain in its scope. Only questions are answered this way: a gate opens only with `approval.resolved`, which never cites a Decision. | validator (schema for `decision_id`) | 8.3, 13.1, FR-AGT-07 |
