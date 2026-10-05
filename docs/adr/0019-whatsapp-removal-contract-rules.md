# ADR-0019: WhatsApp leaves the contract rules (CH-RM)

- Status: Accepted by the user, 2026-10-05 ("accept ADR-0019, option A"; authority: SD-01, PRD supplement 2026-10-05)
- Deciders: architect (proposal). This ADR and BQ-CHRM-2 need explicit acceptance at merge by the
  user, or by the supervisor under the user's recorded delegation; review passes are not acceptance.
- Requirement: CH-RM (issue #379); SEC-06 and FR-HIL-05 as amended (supplement 2.1); PRD 10.1,
  10.3, 10.4
- Supersedes in part: ADR-0005, ADR-0006, ADR-0007, ADR-0013 (one-line notes in each)

## Context
SD-01 takes WhatsApp out of scope: number binding (FR-CHN-02, FR-CHN-03) is removed, and SEC-06 now
reads "gate and T3 approvals need a signed-in web or mobile-web session ... No PIN". Supplement
2.4 keeps `whatsapp` as a valid enum value ("no new code may emit or read it") and asks for no
schema change. The rules still named WhatsApp as a way to authorise. OB-01 opened a T3 gate
answered on WhatsApp when `pin_verified` was true, and it counted a typed `channel.message_in`
from the bound number as an L2 instruction (PI-04, PI-09, ADR-0006, ADR-0007). Neither the
binding nor the PIN exists any more, so those paths would authorise on a channel where Tilo
cannot tell who is sending.

## Decision
1. **Gate answers.** An `approval.resolved` opens a gate only when its `channel` is `web` or
   `mobile_web`, a signed-in session. With `whatsapp` it opens nothing, whatever the tier and
   whatever `pin_verified` says. `pin_verified` stays a required field: producers write `false`
   and no rule reads it. The owner, Approver and Team Lead checks are unchanged.
2. **L2 instruction.** `policy.applied.instruction_id` names only a `world.requested` that the
   owner typed in a signed-in session (`data.channel` `web` or `mobile_web`). A
   `channel.message_in` is never an instruction, on any channel. BQ-56's `option` and
   `card_kind` sub-rules only narrowed that path, so they go with it. The path they once let
   through, the owner's typed WhatsApp answer to a question card, becomes one invalid case. The
   email `channel.message_in` and email `world.requested` cases stay.

   **Provenance replaces what BQ-56 protected.** A `world.requested` has no `card_id`, `card_kind`
   or `option`, so the event cannot show whether the words were really typed as an instruction or
   came from a card tap. The rule now lives in OB-01 and PI-09. A `world.requested` counts only if
   tilo-api wrote it from a signed-in typed-instruction control (the mail card's instruction box or
   the assistant panel), with these properties:
   - `actor` is the session's principal.
   - `channel` comes from the session, never from the client.
   - `destination` is the thread the control is on, set by the UI.

   It is never written from a card option, from text typed on a gate, consent or meeting card (Edit
   first leads to a redraft, OB-05), by a model, or from an inbound mail body. The validator cannot
   check this from the event alone, so the writer enforces it (CH-RM PR 2 adds that test). Nothing
   may emit a mid-run `world.requested` as an instruction until that writer exists, and
   `L2_ACTION_RECORDED` flips only after it (ADR-0013). Single use (PI-10) is unchanged.

   **The owner** is the actor of the world's first `world.requested`. A later one, by anyone,
   never changes it. The reference check and `tilo_policy` take the owner as a parameter
   (`world_owner`), so a second `world.requested` cannot confuse them. Only the text changes.
3. **No schema change.** No `x-version` bump and no regenerated types. The descriptions of
   `approval.resolved`, `channel.message_in`, `policy.applied` and `card` still mention WhatsApp
   paths. Where they disagree with OB-01, the rule and this ADR govern until each schema's next
   bump rewrites its description.
4. **Rules text:** OB-01 and its case list (`contracts/outbox.rules.md`), the EV-04 and L2 lines in
   `contracts/event.rules.md`, the WhatsApp clause in CR-07, and PI-02, PI-04 and PI-09.
5. **Fixtures.** No valid case relies on WhatsApp:
   - The card fixtures drop it from `answer_channels`, and so does the web copy.
   - Gate answers move to `web`, or to `mobile_web` when an Approver answers.
   - L2 instructions become `world.requested` on `mobile_web`, with the same id, time, actor and
     destination, so each invalid case still breaks only its own rule.
   - `notify_channel`, layout island names and the event, common and policy samples use
     email, Email or mobile web.

   The crossref changes are:
   - `ob01_gate_approved_on_whatsapp` and `ob01_l2_instruction_is_a_whatsapp_message` replace
     `ob01_t3_whatsapp_without_pin` and the three card-answer cases.
   - `gate_t3_reply_approved_by_assigned_approver_signed_in` replaces `..._with_pin`.

   A test shows that WhatsApp alone breaks each new invalid case.
6. **Engine and reference check.** Both `tilo_policy.coverage` (`SIGNED_IN`) and
   `test_FR_WLD_03_outbox_crossref.py` use an allowlist, so a legacy or forged WhatsApp answer
   or message fails closed. For web, mobile_web and email, every check stays as it was or gets
   stricter.

## What stays dormant
- `whatsapp` in `common.channel`, in card `answer_channels` (gate and meeting), and in
  `approval.resolved`, `channel.message_in` and `channel.message_out`. Also `pin_verified`, and
  `card_kind`/`option` on `channel.message_in`, which email still records.
- Invalid fixtures that keep the value to show it is refused:
  `card/invalid/consent_answered_on_whatsapp`, `person/invalid/preferred_channel_not_offered`,
  and the two crossref cases above.
- Service code that still emits or reads WhatsApp: tilo-api `runs.py`, `cards.py` (the
  `pin_required` branch), `deps.py` and `dispatch.py`; harness `must_ask.py`; browser
  `login.py`; tilo-channels webhook, binding, cards and keywords. CH-RM PR 2 removes it.

## Consequences
- Nothing over WhatsApp authorises a side effect. tilo-api refuses a WhatsApp answer on any card
  built from the contract fixtures (`invalid_channel`). It takes `channel` `whatsapp` only from an
  authenticated tilo-channels caller, which is not wired. Cards still built with `whatsapp`
  (`runs.py`, `must_ask.py`, `login.py`) are PR 2's. Until then, an answer recorded over
  WhatsApp opens nothing: `open_gate` (runs.py) and `check_entry` (outbox, autopilot) refuse it.
- **L2 sources for tilo-channels (PR 2).** The channels service no longer turns any inbound
  message into an instruction. The Email Autopilot's instruction is the owner's `world.requested`
  from the signed-in mail card or assistant panel (FR-CHN-14 as amended). Its
  `data.destination` is the thread id that the control sets, and `policy.applied.instruction_id`
  names that event. BQ-150's key `(user_id, instruction_id)` therefore keys on that event. An
  inbound email `channel.message_in` is still recorded and may answer a question card, but it
  never opens a send. PI-21 still holds every L2 send at a gate until ADR-0013 is built.
- **ADR-0013.** Decision 2 (a WhatsApp answer copies `action_type`) and its `channel.message_in`
  diff lapse. Decisions 1 and 3 stand: on the web, a fixed control sets `action_type`.
- How a typed answer to "What should I say?" on the web becomes a `world.requested` is logged as
  BQ-CHRM-2. **User decision, 2026-10-05: option A (defer).** No typed mid-run instruction path is
  built for now. A `world.requested` is written only when a person starts a run on the web, and
  every L2 send keeps waiting at a gate (PI-21). A dedicated mid-run instruction event, covering
  its thread, where its words land and its effects (HR-1 to HR-7), gets its own ADR later. The
  architect's earlier default (the mail card or panel writes a mid-run `world.requested`) is NOT
  applied. The three points it raised stay open for that later ADR:
  - who sets a panel instruction's thread;
  - where the instruction's words land (events, Story, archive);
  - the `world.requested` registry effects for a mid-run instruction (HR-1 to HR-7).

  No registry or schema change is made here.
