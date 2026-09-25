# Outbox rules beyond the schema (outbox.schema.json v1)

The outbox is the only path to a side effect (SEC-03): the harness writes an entry once the
deterministic policy engine has authorised it, and `tilo-connectors` runs it exactly once.
Rules marked "schema" are enforced by `outbox.schema.json`; the rest belong to the harness
validator (P0-09) and the connectors service.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| OB-01 | An entry is written only after authorisation: a person or Team Lead answered `approve` on its gate (`approval.resolved`) or a policy opened the gate (`policy.applied`). Its `id` is the `outbox_id` that `approval.requested` reserved, and its `authz` equals that event's `authz`. Nothing waiting at a gate is in the outbox. | validator | SEC-03, 10.4 |
| OB-02 | `scheduled_at` equals `created_at` plus `undo_window_s`. An entry waiting out its undo window is `scheduled`; with no window it is `queued`. | validator | 10.4 (L2), 11.4 (Undo) |
| OB-03 | `idempotency_key` is stable per step and unique per world; a retry reuses it and the connector runs a key at most once, so a retry never sends twice. | connectors | FR-AGT-11, FR-CHN-13 |
| OB-04 | T3 is authorised by a person or Team Lead, never a policy; any modifier makes the entry T3; an attachment is listed as the `attachments` modifier; below T3 there are no modifiers and no attachments. | schema | 10.4, 11.4 |
| OB-05 | The entry is exactly what was authorised. `action_type`, `connector`, `recipients`, `attachments`, `item` and `destination` equal what the gate card showed (card rule CR-12). `item` names the same `artifact_id` and `version` as the `item` of the event that reserved or opened it: `approval.requested` with this `outbox_id`, or `policy.applied` when a policy opened the gate. The policy engine assessed the tier modifiers, `safety_flag` included, on that version. `item` is null only when the action moves no content, such as a delete. A stored artifact version never changes, and the connector sends exactly `item` at its `version`, in `destination`. No field but `state` changes after the entry is written: a redraft (a new version) or any other change is a new proposal with a new gate, also during an undo window. States move `queued` or `scheduled` to `sending`, then `sent` or `failed`; `scheduled` may move to `cancelled` until sending starts. Each sent entry emits one `data.transfer` with direction `out`, this `outbox_id`, the same `authz`, `connector` and `action_type`, and `artifact` equal to `item`. | validator | 10.3, 10.4, 11.4, HR-7 |

Fixtures: `fixtures/outbox/valid/` and `fixtures/outbox/invalid/` (one file per schema rule).
Cross-reference cases for OB-01 and OB-05 are in `fixtures/outbox/crossref/{valid,invalid}/`
(contracts-check skips that folder). Each file holds `rule` (null when valid), `note`, `entry`
(an outbox entry), `authorised_by` (`type` `approval.requested` or `policy.applied`, and that
event's `data`) and `transfer` (the `data` of the `data.transfer` it emitted, or null when not
sent yet). Every part is shape-valid; each invalid file breaks only the rule its name starts
with. `tests/contracts/test_FR_WLD_03_outbox_crossref.py` holds the reference check; the P0-09
validator's tests must run the same files. Card-side cases (the entry against the gate card)
are CR-12's, in `fixtures/card/crossref/`.
