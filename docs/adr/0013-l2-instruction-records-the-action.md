# ADR-0013: An L2 instruction records the action it asks for

- Status: Accepted (2026-10-05, user decision: "yes to all as you think necessary", relayed by the supervisor;
  proposed 2026-10-02 by the architect; issue #28, BQ-57, PI-21). It
  adds fields to frozen contracts (`card.schema.json`, `events/data/channel.message_in`,
  `events/data/world.requested`) and tightens outbox rule OB-01. The user's approval covers that
  change; this status edit does not make it, so `contracts/` is changed by its own architect PR
  (root `CLAUDE.md`). The interim engine rule in BQ-57 is decided and did not wait for this ADR.
- Superseded in part by ADR-0019 (SD-01): decision 2 (a WhatsApp answer copies `action_type`)
  lapses; decisions 1 and 3 stand.
- Deciders: user (approval), architect (proposal)
- Requirement: FR-HIL-05, FR-CHN-11 (PRD 10.4, 11.2, 11.4); follows ADR-0007

## Context
At L2 ("instruction is approval", PRD 10.4), `policy.applied.instruction_id` names the owner's
own instruction. That is either a `world.requested` from a signed-in web session, or a typed
`channel.message_in` from the bound WhatsApp number about the same destination (OB-01, PI-08 to
PI-10, ADR-0007).

Neither event records which action the owner asked for, and deterministic code never reads the
words. So one typed message about a thread can open one covered send of any action type an L2
policy covers there, even "don't reply yet". PRD 10.4 acts only when the instruction "explicitly
asks for the action". PI-21's interim rule (the instruction is no earlier than the history entry
that put the policy at L2) narrows the window but does not close the gap.

Issue #28 named two deterministic sources for the action:
1. The question card that asks "What should I say?" (PRD 11.2) names the action type, and the
   answer inherits it.
2. A fixed preset or intent id that the channel sets from a button payload or a web control,
   never from the text.

## Decision (proposed)
1. **The card names the action its question asks about.** `card.schema.json` gains an optional
   `action_type` (`common.schema.json#/$defs/action_type`). It is allowed only on `needs_you`
   cards: the schema refuses it on gate, consent and meeting cards, and a gate already has
   `gate.action`. The deterministic card builder writes it from the step that raised the card,
   never a model. For example, the triage step for a thread that needs a reply raises
   "What should I say?" with `action_type: send_email`. It is left out when the question asks
   about no action.
2. **A typed WhatsApp answer copies it from the card.** `channel.message_in` data gains an
   optional `action_type`. It is set only when the message answers a `needs_you` card that names
   one, and then equals it. tilo-channels copies it from the card (new card rule CR-14,
   validator). It is never read from the text.
3. **A web request takes it from a fixed control.** `world.requested` data gains an optional
   `action_type`. It is set only when `channel` is `web` or `mobile_web` (schema), and only by a
   fixed control whose id is the action type, such as a Reply button on a thread view. It is
   never derived from the typed title.
4. **OB-01 and PI-08.** At L2, the instruction must carry `data.action_type`, equal to the
   policy's `action_type` (and so to the entry's, OB-05). An instruction without one opens
   nothing. PI-21's history rule stays as an extra check.
5. **Versions.** These are additive fields, so `card` goes to 1.1.0, and `channel.message_in` and
   `world.requested` data go to 1.1.0. OB-01 gets stricter, so the L2 crossref cases change (see
   below). That is why this ADR needs the user's approval.

A left-out field means "asks for no action" (a single spelling, in line with ADR-0011). Leaving
it out fails closed, so existing producers and fixtures stay valid against the schemas.

```diff
 contracts/card.schema.json
-  "x-version": "1.0.0",
+  "x-version": "1.1.0",
 ...
   "properties": {
 ...
+    "action_type": {
+      "description": "needs_you only: the side-effect action type this question asks the person to instruct (PRD 11.2: 'What should I say?' about a thread that needs a reply asks for send_email). Written by the deterministic card builder from the step that raised the card, never by a model; left out when the question asks about no action. A typed answer carries it into channel.message_in, and only then can that answer be an L2 instruction for that action type (OB-01, ADR-0013).",
+      "$ref": "common.schema.json#/$defs/action_type"
+    },
 ...
   "if": { "properties": { "kind": { "const": "gate" } }, "required": ["kind"] },
   "then": {
+    "not": { "required": ["action_type"] },
     ...
   },
   "else": {
     "if": { "properties": { "kind": { "const": "consent" } }, "required": ["kind"] },
-    "then": { ... },
+    "then": { "not": { "required": ["action_type"] }, ... },
     "else": {
       "if": { "properties": { "kind": { "const": "meeting" } }, "required": ["kind"] },
-      "then": { ... },
+      "then": { "not": { "required": ["action_type"] }, ... },
       "else": { ... }
     }
   }
```

```diff
 contracts/events/data/channel.message_in.schema.json
-  "x-version": "1.0.0",
+  "x-version": "1.1.0",
   "properties": {
 ...
+    "action_type": { "$ref": "../../common.schema.json#/$defs/action_type" }
   },
   "if": { "properties": { "card_id": { "type": "null" } }, "required": ["card_id"] },
-  "then": { "properties": { "card_kind": { "type": "null" }, "option": { "type": "null" } } },
+  "then": {
+    "properties": { "card_kind": { "type": "null" }, "option": { "type": "null" } },
+    "not": { "required": ["action_type"] }
+  },
   "else": { "properties": { "card_kind": { "not": { "type": "null" } } } }
```

```diff
 contracts/events/data/world.requested.schema.json
-  "x-version": "1.0.0",
+  "x-version": "1.1.0",
   "properties": {
 ...
+    "action_type": { "$ref": "../../common.schema.json#/$defs/action_type" }
   },
+  "if": { "properties": { "channel": { "enum": ["web", "mobile_web"] } }, "required": ["channel"] },
+  "else": { "not": { "required": ["action_type"] } }
```

```diff
 contracts/outbox.rules.md  (OB-01, L2 sentence)
-... The instruction is of the same world, earlier than `authz.at`, its `actor` is the policy's `owner` and its `data.destination` equals `policy.applied`'s `destination` (never null at L2), ...
+... The instruction is of the same world, earlier than `authz.at`, its `actor` is the policy's `owner`, its `data.destination` equals `policy.applied`'s `destination` (never null at L2) and its `data.action_type` is present and equals the policy's `action_type` (ADR-0013: on WhatsApp copied from the needs_you card the message answers, on the web set by a fixed control, never read from the words), so an instruction that asks for no action, or for another one, opens nothing; ...
```

```diff
 contracts/card.rules.md
+| CR-14 | A `channel.message_in` carries `action_type` only when its `card_id` names a `needs_you` card with an `action_type`, and then the two are equal (tilo-channels copies it from the card; ADR-0013). | validator | 10.4, 11.2, FR-HIL-05 |
```

## Alternatives considered
- **A preset id from a button payload (issue #28 option 2) on WhatsApp.** ADR-0007 decided that a
  tapped option is never an instruction, and that a preset tapped on a question card leads to a
  gate (BQ-56). Making presets count would reopen that decision. They stay out unless the user
  wants it. The web half of option 2, a fixed control, is decision 3.
- **Read the action from the words with a model.** A model would then decide authorisation.
  Never (root `CLAUDE.md`, PRD 10.4).
- **Required, nullable fields** (the style `card_kind` and `option` use). This would be more
  explicit, but every card and message fixture, every producer, and the test-writer's minimal
  payloads would have to change. Since leaving the field out already fails closed, optional is
  enough.
- **Keep PI-21's interim rule only.** It still lets one message open any covered action type.
  Rejected, and BQ-57 replaces it with fail-closed until this ADR lands.

## Migration and fixture impact
- **Schemas:** the diffs above. Regenerate `packages/contracts-py` and `packages/contracts-ts`.
- **Valid fixtures:**
  - Card: `needs_you_compare_basis.json` stays as it is (asks about no action). New
    `needs_you_what_should_i_say.json` with `action_type: send_email`.
  - Events: new `channel.message_in--instruction.json` (typed answer to that card) and
    `world.requested--reply_control.json`.
- **Invalid fixtures:**
  - Card: `gate_with_action_type.json`, `consent_with_action_type.json`,
    `meeting_with_action_type.json`.
  - Events: `channel_message_in_action_type_without_card.json`,
    `world_requested_action_type_by_email.json`.
- **Outbox crossref, valid:** the four L2 cases (`policy_reply_instructed_on_the_web`,
  `policy_reply_sent_after_undo_window`, `policy_reply_sent_before_revocation`,
  `policy_reply_waiting_out_undo_window`) add `action_type: send_email` to their instruction.
- **Outbox crossref, invalid:**
  - Of the ten `ob01_l2_*` cases, those whose instruction answers a `needs_you` card or comes
    from the web add `action_type: send_email`, so each still fails for its own reason. The
    gate-card cases, the email cases and `ob01_l2_policy_without_instruction` leave it out,
    because the schema or CR-14 refuses it there. They still fail OB-01 only.
  - New `ob01_l2_instruction_without_action_type`.
  - New `ob01_l2_instruction_for_another_action_type`.
- **Card crossref:** new CR-14 cases (copied correctly; differs from the card; set while
  answering a gate).
- **Code:**
  - `packages/policy` (`coverage.instruction_counts`) compares `action_type`, and the reference
    check in `tests/contracts/test_FR_WLD_03_outbox_crossref.py` does the same.
  - tilo-channels copies the card's `action_type`.
  - The deterministic card builder sets it on "What should I say?" cards.
- **docs/security/p4-policy-invariants.md:** PI-08 gains the clause, PI-21 closes, and new rows
  are added for CR-14 and the two new cases.

## Consequences
- Unblocks: P0-03b, FR-HIL-05 and FR-CHN-11 (L2 sends with an undo window), and the Email
  Autopilot send path (FR-CHN-10 to FR-CHN-13). Until then, the BQ-57 interim applies: every
  L2-covered send waits at a gate.
- **Residual risk, stated plainly.** The record says what the question asked about, not what the
  person answered. "Don't reply yet", typed in answer to "What should I say?", still carries
  `send_email`. Three things stop a send then:
  - the drafter, which uses only facts from the instruction and asks about anything unclear
    (PRD 11.4);
  - the L2 preview with "Sending in 60 s" and Cancel (PRD 10.4, 11.2, FR-CHN-11);
  - the single-use instruction (PI-10).

  Code checks who sent the instruction, the channel, the destination, the action type and single
  use. No model decides any of them.
- A WhatsApp message typed without a card ("reply yes to Riya" out of the blue) asks for no
  recorded action, so its send waits at a gate. That is L1, the PRD's default level.
