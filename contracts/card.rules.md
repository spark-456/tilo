# Card rules beyond the schema (card.schema.json v1)

PRD 10.3: every card has a timeout and a safe default, and the Director applies the default when
the card times out, with no person involved. So the default must always be an option the card
offers, and it must never be irreversible. `card.schema.json` checks what one document can
express; the deterministic card validator (P1, FR-HIL-01 and FR-HIL-02) also enforces the rules
marked "validator" and rejects a card that breaks any of them before it is posted. A rejected
card is never shown and never times out. Each rule id is stable; a failing validation names it.

| Rule | Rule | Checked by | Source |
| --- | --- | --- | --- |
| CR-01 | `safe_default` names one of `options[].id`. On gate and consent cards the schema already enforces it (the default is `hold` and a `hold` option is required). | validator (schema for gates and consent) | 10.3 |
| CR-02 | Option ids are unique within a card. On gate cards the schema enforces it (CR-07); on every card it requires each `hold` option to be reversible, so a repeated `hold` id cannot put an irreversible action behind the default. | validator (schema for gates and `hold`) | 10.3 |
| CR-03 | The safe-default option has `irreversible: false`. Only a gate card may offer an irreversible option, since every irreversible action maps to a gate (`plan.rules.md` PG-04), and a gate's `hold` option must be reversible. With CR-01 and CR-02 this makes every card's default reversible. | schema | 10.3 |
| CR-04 | A gate's and a consent card's safe default is `hold`: a gate never times out to "go", and a consent card never times out to granting the connection ("That connection waits"). | schema | 10.2, 10.3 |
| CR-05 | 2 to 3 options, exactly one suggested; the suggested option has a reason and is never irreversible. | schema | 10.3 |
| CR-06 | Gate and consent cards offer no "Delegate to Director" action: approving a side effect and granting a connection are authorisations, and a model never authorises. | schema | 10.3, 10.4 |
| CR-07 | A gate's option ids come from a closed set, each at most once: `approve`, `edit`, `hold`. `approve` and `hold` are required. Only `approve` opens the gate. `edit` and `hold` leave it closed and are reversible. Each id has a fixed label: `approve` is "Approve", `edit` is "Edit first", `hold` is "Hold". The person reads the label and taps it, and that tap is the authorisation, so no one (model or code) writes a gate label; WhatsApp shows only labels on its buttons. | schema (ids, counts, labels); policy engine (only `approve` opens) | 10.3, 10.4 |
| CR-08 | `approve.irreversible` equals `gate.irreversible`. With CR-05 this means that on an irreversible gate `approve` is never suggested. On a reversible gate it may be. | schema | 10.3 |
| CR-09 | `gate.id` names a gate of the run's PlanGraph, and `gate.action.type` equals that plan gate's `action_type`. | validator | 10.4, FR-INT-09 |
| CR-10 | `gate.action.connector` names a connector in `config/connectors.yaml` that declares an action whose `id` is `gate.action.type` with `gate_type: approval`, and `gate.irreversible` equals that action's `irreversible`. | validator | 10.4, 12.1 |
| CR-11 | `gate.risk_tier` equals the plan gate's `risk_tier` (PG-06), raised to T3 when any risk-tier modifier (`policy.schema.json#/$defs/tier_condition`) applies to the held side effect, for example a new recipient. Never lower. | validator | 10.4, FR-HIL-04 |
| CR-12 | The gate card shows exactly what the gate releases, the outbox entry whose id is the `outbox_id` that `approval.requested` reserved (`outbox.schema.json`). `gate.recipients` equals the entry's `recipients` as a set: no one added, no one left out. `gate.action.item` names the same `artifact_id` and `version` as the entry's `item` and the `item` that `approval.requested` reserved, and `gate.action.destination` equals the entry's `destination`. The entry is written only when the gate opens, with exactly these values; a redraft is a new proposal with a new card (outbox rules OB-01, OB-05). | validator | 10.3, 10.4, 11.4 |
| CR-13 | A consent card's option ids are the closed set `connect` and `hold`, each exactly once, with fixed labels: `connect` is "Connect", `hold` is "Hold". The person taps the label (and a consent tap is an authorisation), so no one writes a consent label. Only `connect` grants the connection (`connection.consented`); `hold` leaves it waiting. | schema (ids, counts, labels); connector token broker (only `connect` grants) | 10.2, 10.3, 10.4 |

**Who writes a gate card.** The deterministic card builder (P1) writes every field of `gate`
(including `action.exact`, `action.item` and `action.destination`) and the gate options, copying them from the plan
gate, the connector declaration and the proposed side effect (the outbox entry the gate will
release). A model writes none of them; it may write `what_happened` and `why_it_matters`. The
card validator checks CR-09 to CR-12 before a gate card is posted, so a card that shows a send
as a reversible T1 draft is never shown. The same builder writes a consent card's options.

Cross-reference cases for CR-09 to CR-12 are in `fixtures/card/crossref/{valid,invalid}/`. Each
file holds `rule` (null when valid), `note`, `plan_gates`, `connectors` (id and declared
actions), `held` (the `recipients`, `modifiers`, `item` and `destination` of the outbox entry
the gate releases) and `card_gate`. Every part is shape-valid; each invalid file breaks only the rule its name starts
with.
`tests/contracts/test_PRD_10_3_gate_card_labels_and_crossref.py` holds the reference check; the
P1 card validator's tests must run the same files.

Every file in `fixtures/card/invalid/` must fail the schema (FR-WLD-02 tests), so CR-01 and
CR-02 have no fixture there: a needs-you or meeting card whose default names no option, or a
non-gate card that repeats an option id, is schema-valid. The P1 card validator's tests must cover
both rules, and the policy engine's tests must show that only `approve` opens a gate (CR-07). The schema-checked parts have invalid fixtures (`gate_approve_reversible_on_irreversible_gate`,
`gate_approve_suggested_on_irreversible_gate`, `gate_approve_irreversible_on_reversible_gate`,
`gate_without_approve_option`, `gate_option_id_outside_closed_set`, `gate_approve_option_twice`,
`gate_edit_option_irreversible`, `gate_duplicate_hold_option_irreversible`,
`gate_approve_option_labelled_hold`, `gate_hold_option_labelled_send_it`,
`gate_edit_option_labelled_keep_draft`,
`consent_without_hold_option`, `consent_option_id_outside_closed_set`,
`consent_connect_option_labelled_allow_access`, `consent_hold_option_labelled_not_now`,
`consent_hold_option_twice`, `safe_default_irreversible`, `meeting_option_irreversible`,
`gate_hold_option_irreversible`, `gate_safe_default_go`, `consent_safe_default_connect`,
`suggested_option_irreversible`, the option-count files, `gate_delegated_to_director` and
`consent_delegated_to_director`). The policy engine's and token broker's tests must show that
only `connect` grants a connection (CR-13).
