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
| OB-05 | `action_type`, `connector`, `recipients` and `attachments` equal what the gate card showed (card rule CR-12); any change is a new proposal with a new gate. States move `queued` or `scheduled` to `sending`, then `sent` or `failed`; `scheduled` may move to `cancelled` until sending starts. Each sent entry emits one `data.transfer` with direction `out`, this `outbox_id` and the same `authz`. | validator | 10.3, 11.4, HR-7 |

Fixtures: `fixtures/outbox/valid/` and `fixtures/outbox/invalid/` (one file per schema rule).
