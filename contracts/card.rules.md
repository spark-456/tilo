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
| CR-07 | A gate's option ids come from a closed set, each at most once: `approve`, `edit`, `hold`. `approve` and `hold` are required. Only `approve` opens the gate. `edit` and `hold` leave it closed and are reversible. The policy engine and the channel handlers read the option id only, never its label, so a mislabelled option cannot open a gate. | schema (the id set and counts); policy engine (only `approve` opens) | 10.3, 10.4 |
| CR-08 | `approve.irreversible` equals `gate.irreversible`. With CR-05 this means that on an irreversible gate `approve` is never suggested. On a reversible gate it may be. | schema | 10.3 |

Every file in `fixtures/card/invalid/` must fail the schema (FR-WLD-02 tests), so CR-01 and
CR-02 have no fixture there: a needs-you or meeting card whose default names no option, or a
non-gate card that repeats an option id, is schema-valid. The P1 card validator's tests must cover
both rules, and the policy engine's tests must show that only `approve` opens a gate (CR-07). The schema-checked parts have invalid fixtures (`gate_approve_reversible_on_irreversible_gate`,
`gate_approve_suggested_on_irreversible_gate`, `gate_approve_irreversible_on_reversible_gate`,
`gate_without_approve_option`, `gate_option_id_outside_closed_set`, `gate_approve_option_twice`,
`gate_edit_option_irreversible`, `gate_duplicate_hold_option_irreversible`,
`consent_without_hold_option`, `safe_default_irreversible`, `meeting_option_irreversible`,
`gate_hold_option_irreversible`, `gate_safe_default_go`, `consent_safe_default_connect`,
`suggested_option_irreversible`, the option-count files, `gate_delegated_to_director` and
`consent_delegated_to_director`).
