# Outbox rules beyond the schema (outbox.schema.json v1)

The outbox is the only path to a side effect (SEC-03): the harness writes an entry once the
deterministic policy engine has authorised it, and `tilo-connectors` runs it exactly once.
Rules marked "schema" are enforced by `outbox.schema.json`; the rest belong to the harness
validator (P0-09) and the connectors service.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| OB-01 | An entry is written only after authorisation, and carries that authorisation unchanged. On a gate, `approval.requested` reserved the entry's `id` as its `outbox_id`, and the entry's `authz` equals the `authz` of the `approval.resolved` that answered `approve` on that gate (same `gate_id`, `card_id` and `outbox_id`): the person or Team Lead who tapped approve. Without a gate, the entry's `authz` equals the `authz` of the `policy.applied` with this `outbox_id` (by `policy`, `ref` equal to its `policy_id`, EV-06), and the policy named by `policy_id` covers the entry, since no person saw it: the policy has the `policy.applied`'s `action_type`, `level` and `undo_window_s` and had not expired at `authz.at`; `policy.applied`'s `connector` is in `scope.connectors` and its `district` in `scope.districts`; every one of the entry's `recipients` is in `scope.recipients` and at a domain in `scope.domains` (exact match); an empty scope list does not restrict. The engine opens it only while the policy's actions that day, this one included, stay within `limits.per_day` and their credits within `limits.credits`; otherwise it waits at a gate (FR-HIL-03, FR-HIL-06). A new recipient is T3 (OB-04), so no policy scope covers one. `approval.requested` never authorises (its `authz` is null, EV-05): a gate answered `edit` or `hold`, or not answered, writes nothing, and an entry that `approval.requested` reserved is opened only by `approval.resolved`. The `data.transfer` out that a sent entry emits carries the entry's `authz`, so a policy action is never shown as a person's approval or the reverse. Nothing waiting at a gate is in the outbox. | validator; policy engine (limits) | SEC-03, 10.4, FR-HIL-05, HR-7 |
| OB-02 | `scheduled_at` equals `created_at` plus `undo_window_s`. An entry waiting out its undo window is `scheduled`; with no window it is `queued`. | validator | 10.4 (L2), 11.4 (Undo) |
| OB-03 | `idempotency_key` is stable per step and unique per world; a retry reuses it and the connector runs a key at most once, so a retry never sends twice. | connectors | FR-AGT-11, FR-CHN-13 |
| OB-04 | T3 is authorised by a person or Team Lead, never a policy; any modifier makes the entry T3; an attachment is listed as the `attachments` modifier; below T3 there are no modifiers and no attachments. | schema | 10.4, 11.4 |
| OB-05 | The entry is exactly what was authorised. On a gate, `action_type`, `connector`, `recipients`, `attachments`, `item` and `destination` equal what the gate card showed (card rule CR-12). On either path, `action_type`, `risk_tier` and `item` (the same `artifact_id` and `version`) equal those of the event that reserved or opened it: `approval.requested` with this `outbox_id`, or `policy.applied` when a policy opened the gate. With no gate card on the policy path, `connector`, `destination` and `undo_window_s` also equal `policy.applied`'s, and at L2 that window is at least 1 s (`policy.applied` schema), so a policy send never loses its undo window, changes thread or connector, or changes tier. The policy engine assessed the tier modifiers, `safety_flag` included, on that version. `item` is null only when the action moves no content, such as a delete. A stored artifact version never changes, and the connector sends exactly `item` at its `version`, in `destination`. No field but `state` changes after the entry is written: a redraft (a new version) or any other change is a new proposal with a new gate, also during an undo window. States move `queued` or `scheduled` to `sending`, then `sent` or `failed`; `scheduled` may move to `cancelled` until sending starts. Each sent entry emits one `data.transfer` with direction `out`, this `outbox_id`, the same `connector` and `action_type`, and `artifact` equal to `item` (its `authz` is OB-01's). | validator | 10.3, 10.4, 11.4, HR-7 |

Fixtures: `fixtures/outbox/valid/` and `fixtures/outbox/invalid/` (one file per schema rule).
Cross-reference cases for OB-01 and OB-05 are in `fixtures/outbox/crossref/{valid,invalid}/`
(contracts-check skips that folder). Each file holds `rule` (null when valid), `note`, `entry`
(an outbox entry), three event parts, each `{type, authz, data}` as the event carries them or
null: `reserved_by` (the `approval.requested`, null when a policy opened the entry),
`authorised_by` (the `approval.resolved` or `policy.applied` that opened it, null when the gate
was never answered) and `transfer` (the `data.transfer` it emitted, null when not sent yet), and
`policy` (the `policy.schema.json` record `policy.applied` names, null on a gate path).
Every part is shape-valid and passes EV-03 to EV-06; each invalid file breaks only the rule its
name starts with. The OB-01 cases cover a gate answered `hold`, a gate never answered, an
approval of another gate, `authz` from another person or from a Team Lead instead of the person,
a policy send stamped as a person, a person's approval stamped as a policy, a send stamped
differently from its entry, and a policy send to a recipient, connector or district outside the
policy's scope or under an expired policy. The OB-05 policy cases cover a dropped undo window, a
different tier, a thread reply turned into a new email and a send on another connector than the
one assessed. `tests/contracts/test_FR_WLD_03_outbox_crossref.py` holds the
reference check; the P0-09 validator's tests must run the same files. Card-side cases (the entry
against the gate card) are CR-12's, in `fixtures/card/crossref/`.
