# ADR-0009: Owner-only event visibility, and the card on `question.answered`

- Status: Accepted (2026-10-05, user decision: "yes to all as you think necessary", relayed by the supervisor;
  proposed 2026-10-02 by the architect; issue #125, BQ-73). It changes
  frozen contracts (`event.schema.json`, `events/data/question.answered.schema.json`,
  `events/registry.yaml`, `event.rules.md`). The user's approval covers that change; this status
  edit does not make it, so `contracts/` is changed by its own architect PR (root `CLAUDE.md`,
  ADR-0002 decision 2).
- Deciders: user (approval), architect (proposal)
- Requirement: FR-HIL-01, FR-HIL-02, FR-HIL-09, FR-HIL-11, FR-CHN-05, SEC-07 (PRD 9.3, 9.5, 9.6,
  10.1, 10.3, 15.3)
- Lands with: ADR-0012 (issue #29). Both change EV-13 and `vis`, so they belong in one contracts
  PR and one version bump of `event.schema.json`.

## Context
1. **`vis` cannot say "owner only".** `vis` is `"all"` or `district_list`, which has
   `minItems: 1`. The cards API (PR #121) raises cards with no known district, and BQ-69 makes
   such a card owner-only. Its event therefore has no valid `vis`. Today the API writes the part
   with `vis: None` and a part-level `owner_only: True`, and tells the writer never to default it
   to `"all"` (`services/api/src/tilo_api/cards.py`, `_part`). An event with `vis: None` fails
   the schema, so every writer has to special-case a flag the contract does not describe.
2. **`question.answered` does not say which card was answered.** Its data is
   `{answered_by, decision_id}`. The registry's HUD effect says "The question card closes on
   every channel", but nothing in the event names the card. The card id travels as a part-level
   companion key, and the channels lane reads it from the API event writer as a workaround. The
   Trace (PRD 9.6) and the decision log (13.2) also cannot show which option was chosen, or
   which safe default a timeout applied (FR-HIL-02 "applies its default and posts a Nudge").

## Decision (proposed)
1. **Owner-only is the empty list.** `event.schema.json` `$defs.district_list` drops
   `minItems: 1`. `vis: []` means no scoped view carries the event and only the owner's full
   stream does (PRD 15.3). No new literal is added. Existing readers already treat `[]` as
   owner-only: `services/harness/src/tilo_harness/views.py` (`scope in vis`) and
   `services/api/src/tilo_api/redaction.py` (`_visible`) both return false for it.
2. **EV-13** allows an empty list only when `district` is null. With ADR-0012, an event in a
   district always has a non-empty list that includes that district.
3. **`question.answered` names its card and option.** Two required fields are added to `data`:
   - `card_id` (ULID): the card the person saw, raised by an earlier `question.routed` with the
     same `card_id`. For a merged group (BQ-74) it is the group's first card.
   - `option` (option id or null): the option tapped, or the `safe_default` applied at timeout.
     It is null when the person typed a free answer or a Decision answered (FR-AGT-07).

   When `answered_by` is `default`, `option` must be set (schema) and must equal the card's
   `safe_default` (validator).
4. **New rule EV-15 (validator).** It has three parts:
   - `card_id` is the `card_id` of an earlier `question.routed` in the same world.
   - No two `question.answered` events of a world name the same `card_id`.
   - With `answered_by` `default`, `option` equals that card's `safe_default`. With `person` or
     `team_lead` and a non-null `option`, the option is one of that card's option ids.

   Event-rule ids are separate from the PRD 3.5 metric ids, as EV-01 to EV-14 already are.
5. **Registry.** The `question.answered` `trace_row` becomes
   `card={data.card_id} answered_by={data.answered_by} option={data.option}`. The world effect,
   HUD effect and Story template are unchanged.

```diff
 contracts/event.schema.json
-  "x-version": "1.0.0",
+  "x-version": "1.1.0",
 ...
     "vis": {
-      "description": "Server-side redaction scope (PRD 10.1): all, or the districts whose viewers may see it; a list includes the event's own district (EV-13).",
+      "description": "Server-side redaction scope (PRD 10.1, 15.3): all, or the districts whose viewers may see it; a list includes the event's own district (EV-13). An empty list puts the event in no scoped view: only the owner's full stream carries it (owner-only, for example a card with no known district, BQ-69); it is allowed only when district is null (EV-13).",
       "anyOf": [{ "const": "all" }, { "$ref": "#/$defs/district_list" }]
     },
     "district_list": {
       "type": "array",
-      "minItems": 1,
       "uniqueItems": true,
       "items": { "$ref": "common.schema.json#/$defs/district_id" }
     },
```

```diff
 contracts/events/data/question.answered.schema.json
-  "x-version": "1.1.0",
+  "x-version": "2.0.0",
 ...
-  "required": ["answered_by"],
+  "required": ["answered_by", "card_id", "option"],
   "properties": {
     "answered_by": { "$ref": "../../event.schema.json#/$defs/answer_source" },
+    "card_id": { "$ref": "../../common.schema.json#/$defs/ulid" },
+    "option": {
+      "anyOf": [{ "$ref": "../../card.schema.json#/$defs/option_id" }, { "type": "null" }]
+    },
     "decision_id": {
       "anyOf": [{ "$ref": "../../common.schema.json#/$defs/ulid" }, { "type": "null" }]
     }
   },
   "if": { "properties": { "answered_by": { "const": "decision" } }, "required": ["answered_by"] },
   "then": { ...unchanged... },
-  "else": { "properties": { "decision_id": { "type": "null" } } }
+  "else": {
+    "properties": { "decision_id": { "type": "null" } },
+    "if": { "properties": { "answered_by": { "const": "default" } }, "required": ["answered_by"] },
+    "then": { "properties": { "option": { "$ref": "../../card.schema.json#/$defs/option_id" } } }
+  }
```

The nested `if` sits inside `else`, not in a root `allOf`, so the generated TypeScript stays a
plain type (see the architect's contract pitfalls).

```diff
 contracts/events/registry.yaml  (question.answered)
-    trace_row: "answered_by={data.answered_by}"
+    trace_row: "card={data.card_id} answered_by={data.answered_by} option={data.option}"
```

```diff
 contracts/event.rules.md
+| EV-15 | `question.answered` names the card it answers: `data.card_id` is the `card_id` of an earlier `question.routed` of the same world (for a merged group, BQ-74, the group's first card), and no two `question.answered` of a world name the same `card_id`. With `answered_by` `default`, `data.option` is that card's `safe_default` (schema: not null); with `person` or `team_lead` and a non-null `option`, it is one of that card's option ids. | schema (`option` set on default); validator | 9.5, 9.6, 10.3, FR-HIL-02, FR-HIL-11 |
```

## Alternatives considered
- **`vis: "owner"` as a third literal.** It is explicit, but every reader must handle a new shape.
  Code that does `scope in vis` would run a substring test on the string `"owner"`. The empty
  list says the same thing, and today's readers already treat it as owner-only.
- **`vis: null`, as the current workaround writes.** It reads as "not set" and invites a writer
  default of `"all"`, which is the leak BQ-73 guards against. Rejected.
- **Keep the part-level `owner_only` flag.** The stored event would not be described by the
  contract, and every reader would need to know about the flag. Rejected.
- **Make `card_id` optional** (a minor bump that keeps today's fixtures and tests valid). An event
  could still leave out the card, so the channels workaround would stay possible and the Trace
  would still have gaps. Rejected.
- **A separate `default_applied` boolean.** It would duplicate `answered_by: default`. Rejected.

## Migration and fixture impact
- **Contracts, once approved:** the diffs above. In `scripts/contracts_events.py`, EV-13 refuses
  `[]` with a district (this falls out of ADR-0012's check), and EV-15 is added as a stream
  check. Regenerate `packages/contracts-py` and `packages/contracts-ts`:
  - `EventDistrictList` loses `min_length=1`. In TypeScript it changes from
    `[DistrictId, ...DistrictId[]]` to `DistrictId[]`, so any `vis[0]` use shows up at compile
    time.
  - `QuestionAnsweredData` gains `card_id` and `option`.
- **Valid fixtures:**
  - Add `card_id` and `option` to `fixtures/events/valid/question.answered.json` (`option` from a
    tapped answer) and to `question.answered--from_decision.json` (`option: null`).
  - New `question.answered--default.json` (severity `nudge`, `option` is the safe default).
  - New owner-only `question.routed--owner_only.json` (`district: null`, `vis: []`).
- **Invalid fixtures:**
  - Add the two fields to the three `fixtures/events/invalid/question_answered_*.json` and to
    `fixtures/events/registry/invalid/ev08_default_answer_not_a_nudge.json`, so each still fails
    only its own rule.
  - New `invalid/question_answered_without_card_id.json`.
  - New `invalid/question_answered_default_without_option.json`.
  - New `registry/invalid/ev13_empty_vis_with_district.json`.
- **EV-15 crossref cases:** they compare events with a card, so they go in
  `fixtures/events/crossref/{valid,invalid}/`, with a named reference check. Cases:
  - the answer names no routed card;
  - a second answer for the same card;
  - a default that is not the safe default;
  - an option the card does not offer.
- **Producers:**
  - `services/api/src/tilo_api/cards.py` writes `vis: []` for a card with no district, drops
    `owner_only`, and puts `card_id` and `option` in `question.answered` data.
  - `services/channels` reads `card_id` from the event's `data` and drops the API-writer
    workaround.
  - The harness writer needs no owner-only special case.
- **Tests that pin today's payloads** need the test-writer, since a builder may not weaken them:
  - `tests/contracts/test_BQ_03_BQ_04_event_data_payloads.py` (instances `{"answered_by": "default"}`);
  - `services/api/tests/test_FR_HIL_01_answering.py` (line 93);
  - `services/api/tests/test_FR_HIL_01_scope_and_concurrency.py` (lines 131 and 173, and the
    `owner_only` / `vis is None` assertions);
  - `services/api/tests/test_FR_HIL_02_timeouts.py` (line 42).
- **No stored data to migrate:** nothing is persisted outside local emulators (ADR-0003), and
  their state is reset.

## Consequences
- Unblocks:
  - FR-HIL-11 and FR-CHN-05: a card closes on every channel from the event alone.
  - FR-HIL-09 and SEC-07: owner-only events are excluded by the contract, not by a flag.
  - FR-HIL-02 and the Trace (FR-WLD-06): the Trace shows which card was answered and which
    default applied.
  - FR-HIL-08 and FR-MEM-08: every answer can be traced to its card.
- BQ-73's workaround (`vis: None` plus `owner_only`) is removed.
- `question.answered` data becomes 2.0.0, a breaking change. `event.schema.json` becomes 1.1.0,
  because it now accepts an empty list. `v` stays `"1.0"` (PRD 9.3).
