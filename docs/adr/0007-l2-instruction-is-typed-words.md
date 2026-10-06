# ADR-0007: An L2 instruction is the owner's own typed words

- Status: Accepted (2026-09-25, architect; ticket P0-03, code review after issue #21).
  Freezes with the CP0 set on 29 Sep.
- Superseded in part by ADR-0019 (SD-01): a `channel.message_in` is never an L2 instruction, so
  the typed-words rule for WhatsApp lapses.
- Deciders: architect, orchestrator
- Requirement: FR-WLD-03 (PRD 10.3, 10.4, 11.2, FR-HIL-05, CR-07)

## Context
At L2 ("instruction is approval", PRD 10.4) `policy.applied.instruction_id` names the owner's
earlier `world.requested` (web, signed in) or `channel.message_in` (bound WhatsApp number) about
the same destination (OB-01, PI-08, PI-09). A button tap on a WhatsApp card also arrives as
`channel.message_in`, with `card_id` and the card's `destination` but no record of the option
tapped. Tapping Hold on a gate card, or any reply button on a question card, therefore looked
the same as a typed "send it" and could open an L2 send. That breaks CR-07 (only `approve` opens
a gate). A valid crossref case even used a card answer as its instruction. Excluding every card
answer would also break the PRD's own flow. In 11.2 Tilo asks "What should I say?" on WhatsApp
and the owner's typed answer is the instruction. That question is a card (10.3: every request
uses one card). BQ-56 has the details.

## Decision
1. `channel.message_in` records `card_kind` (the kind of the card it answers, copied from that
   card by the channels service; null when `card_id` is null) and `option` (the id of the reply
   button tapped, taken from the button payload; null when the person typed the message). The
   schema ties both to `card_id`. Neither field is ever read from the text or set by a model.
2. At L2, a `channel.message_in` counts as an instruction only when `option` is null and
   `card_kind` is null or `needs_you`. The rest of OB-01 still applies (WhatsApp, the owner, the
   same world, earlier, the same destination, not used before). A tapped option is an answer that
   its own event records (`approval.resolved`, `connection.consented`, `question.answered`). A
   typed answer to a gate, consent or meeting card belongs to that card; for example, Edit first
   leads to a redraft, which is a new proposal with a new gate (OB-05). Neither is an instruction.
   A preset tapped on a question card is not one either, so that send waits at a gate.
3. Cases: `fixtures/outbox/crossref/invalid/ob01_l2_instruction_is_a_gate_card_hold`,
   `ob01_l2_instruction_is_a_tapped_question_option` and `ob01_l2_instruction_typed_on_a_gate_card`,
   plus the event fixtures `channel_message_in_option_without_card` and
   `channel_message_in_card_answer_without_kind`. The reference check is `_typed_by_owner` in
   `tests/contracts/test_FR_WLD_03_outbox_crossref.py`.

## Consequences
- The channels service sets `card_kind` and `option` on every inbound message. The policy engine
  (P4) and the P0-09 validator apply the rule before counting an instruction.
- Still open (BQ-57, PI-21, issue #28): an instruction records no action asked for, so a typed
  message about a thread can open one covered send of any covered action type there. The engine
  default until a contract field exists is that the instruction is no earlier than the `history`
  entry that put the policy at L2.
- Pre-freeze change, so `channel.message_in` stays 1.0.0 (ADR-0002). `card.schema.json` moves
  its `kind` enum to `$defs/kind` so that both schemas share it. Validation is unchanged, and the
  generated types gain `CardKind`.
