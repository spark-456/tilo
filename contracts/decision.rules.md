# Decision rules beyond the schema (decision.schema.json v1)

PRD 8.3 and 13.1: an owner's or Team Lead's answer becomes a Decision, and a later question
like it is answered from the Decision with a citation (FR-AGT-07). A reused answer reaches
nobody, so these rules keep it inside the authority, scope and time of the original answer, and
check that authority again wherever and whenever the answer is reused, as outbox OB-01 checks an
answer to a gate. `decision.schema.json` checks one document; `tilo-api` checks DC-01 to DC-03
before it writes a Decision, and the harness checks DC-04 before it emits `question.answered`
with `answered_by: decision` (P7 validator tests cover them). The owner of a world is the actor
of its `world.requested`. Rule ids are stable.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| DC-01 | A Decision records the answer to `source.card_id`, a card of `source.world_id` and `source.run_id`, a world of the org `org_id`. `answered_by` is who gave that answer (the `question.answered` actor, or the `authz` of `approval.resolved`) and `answered_by.at` is when. Only an owner's or a Team Lead's answer becomes a Decision (PRD 13.1): `answered_by.by` is `person` or `team_lead`, never a policy or a model (schema), and a `person` answer makes a Decision only when `answered_by.ref` is the owner of `source.world_id`. An Approver answers the cards assigned to them and no others (PRD 10.1), so their answer, like one applied by default or taken from a Decision, makes no Decision. A person's Decision covers only worlds of `org_id` that person owns: each world `scope.worlds` lists is one, and `all` means all of them. | validator (schema for `by`) | 8.3, 10.1, 13.1, FR-MEM-08 |
| DC-02 | A Team Lead's Decision: `answered_by.ref` names a `team_lead.schema.json` record, as it stood at `answered_by.at`, whose `domain` equals the Decision's `domain` (never null, schema) and which the owner of `source.world_id` assigned (`assigned_by.by`) no later than `answered_by.at`, as outbox OB-01 requires for a Team Lead's answer. The Decision covers only worlds of `org_id` that same owner owns: each world `scope.worlds` lists is one, and `all` means all of them. | validator (schema for non-null `domain`) | 8.3, 10.1, 16.2 |
| DC-03 | `created_at` is no earlier than `answered_by.at`; `expires_at`, when set, is later than `created_at`. | validator | 13.1 |
| DC-04 | `question.answered` with `answered_by: decision` cites in `data.decision_id` (schema) a Decision of the world's org that was created before the event's `ts`, has not expired at `ts`, and whose `scope` covers the event's world and district. The answerer must still be able to answer in that world at `ts`: a `person` Decision answers only when `answered_by.ref` is that world's owner; a Team Lead's Decision answers only when the Team Lead record `answered_by.ref` names still exists at `ts` (removing a Team Lead deletes the record), still has the Decision's `domain`, and was assigned by that world's owner no later than `answered_by.at` (so a Team Lead removed and assigned again later brings back no earlier Decision), and only questions routed with its `domain` (`question.routed` `data.domain`). An owner's Decision answers any domain in its scope. Only questions are answered this way: a gate opens only with `approval.resolved`, which never cites a Decision. | validator (schema for `decision_id`) | 8.3, 10.1, 13.1, 16.2, FR-AGT-07 |

Fixtures: `fixtures/decision/valid/` and `fixtures/decision/invalid/` (one file per schema rule);
`fixtures/events/valid/question.answered--from_decision.json` cites
`fixtures/decision/valid/owner_answer_all_worlds.json`.

Cross-reference cases for DC-01 to DC-04 are in `fixtures/decision/crossref/{valid,invalid}/`
(contracts-check skips that folder). Each file holds `rule` (null when valid), `note`, `decision`
(a Decision), `worlds` (each world of the case, by id, with its `org_id` and `owner`: the
source world, the worlds `scope.worlds` lists and the world of the repeat question),
`team_lead_at_answer` (the `team_lead.schema.json` record `answered_by.ref` named at
`answered_by.at`; null for a person's Decision) and `reuse` (null when only the Decision's
writing is checked, otherwise `answered`, the repeat question's `question.answered` as `{ts,
world_id, district, data}`, `routed`, its `question.routed` as `{data}`, and `team_lead`, the
Team Lead record `answered_by.ref` names at `ts`, null for a person's Decision or when the Team
Lead was removed). Every part is shape-valid; each invalid file breaks only the rule its name
starts with. The DC-01 cases cover an Approver's answer kept as a Decision and an owner's
Decision scoped to another owner's world; the DC-02 cases a Team Lead assigned by another owner
and a Team Lead's Decision scoped to another owner's world. The DC-04 cases cover a removed Team
Lead, one removed and assigned again after the answer, one whose domain changed, a Team Lead's
and an owner's Decision reused in another owner's world, an Approver's Decision from a world
they own reused in a world where they are only an Approver, and a Team Lead's Decision on a
question of another domain. The valid cases reuse an owner's Decision in another of the owner's
worlds on another domain's question, and a Team Lead's Decision in its world and domain and in
another world of the owner who assigned them.
`tests/contracts/test_FR_AGT_07_decision_crossref.py` holds the reference check; the P7
validator's tests must run the same files.
