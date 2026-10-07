# ADR-0009: Owner-only event visibility, and the card on `question.answered`

- Status: Accepted (2026-10-05, user decision: "yes to all as you think necessary", relayed by the supervisor;
  proposed 2026-10-02 by the architect; issue #125, BQ-73). It changes
  frozen contracts (`event.schema.json`, `events/data/question.answered.schema.json`,
  `events/registry.yaml`, `event.rules.md`). The user's approval covers that change; this status
  edit does not make it, so `contracts/` is changed by its own architect PR (root `CLAUDE.md`,
  ADR-0002 decision 2).
- Amendment 1 (2026-10-07): **Proposed**, awaiting the user's approval. It lands decision 1 alone
  (`district_list` may be empty, event 1.2.0); see "Amendment 1" at the end of this file.
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

## Amendment 1 (2026-10-07): land decision 1 alone

- Status: **Proposed** (architect, 2026-10-07). It changes a frozen contract
  (`event.schema.json`), so it waits for the user's approval on its PR, "ADR-0009: district_list
  may be empty (Proposed)". The acceptance of 2026-10-05 covered the whole ADR; this amendment
  changes what lands and when, so it goes back to the user.
- Requirement: PE-12 and PE-30 (`docs/prd-addendum-people-agents.md`), FR-HIL-09, SEC-07; ticket
  PPL-11c S5.

### Context
1. The architect PR that the status above asks for never landed. Since then:
   - `event.schema.json` went to 1.1.0 for ADR-0022 (EFF-04), so the 1.0.0 to 1.1.0 diff above
     is stale.
   - ADR-0018 took event-rule id EV-15 (artifact versions) and ADR-0022 took EV-16, so decision 4's
     EV-15 is no longer free.
2. PPL-11c S5 needs decision 1 now. PE-12 (`contracts/people.rules.md` line 39) says these events
   "carry `vis: []` wherever `district` is null" once this ADR lands. `services/api/tests/API_PPL_11c.md`
   (lines 177 to 188) and BQ-PPL11C-7 pin `vis: []` on the Desk-world `work_item.created` and
   `work_item.changed`. The dev-mode test
   `test_PPL_11c_s5_PE_12_dev_mode_records_the_work_item_event_in_the_dev_owners_desk_world` skips
   while `district_list` has `minItems: 1`.
3. Decisions 3 to 5 (`card_id` and `option` on `question.answered`) are a breaking change (data
   2.0.0). The tests that pin today's payloads (listed above) need the test-writer first. Holding
   S5 back for them gains nothing.

### Decision (proposed)
1. **Land decision 1 alone.** `event.schema.json` `$defs.district_list` drops `minItems: 1`.
   Nothing else about `vis` changes: it stays required, `"all"` stays its only other value, null
   stays refused, and a list stays unique and made of district ids. `x-version` goes from 1.1.0
   to 1.2.0. That is minor (ADR-0002 decision 2): the schema accepts one more value and refuses
   nothing it accepted before. It is also the next free minor (ADR-0002 decision 15). `v` stays
   `"1.0"`. The `vis` description now says what an empty list means.
2. **Decision 2 needs no code.** EV-13's existing check already refuses `[]` with a district, since
   the list must include the district: `scripts/contracts_events.py` lines 89 to 90 and
   `services/harness/src/tilo_harness/validator.py` lines 404 to 405. EV-13's text now says so,
   and `fixtures/events/registry/invalid/ev13_empty_vis_with_district.json` pins it.
3. **Decisions 3 to 5 stay accepted but unlanded.** They go in their own PR, with the test-writer's
   payload changes. Their rule takes the next free id (EV-17 today), not EV-15.
4. **ADR-0012 is not in this PR.** It changes no schema keyword, only rule text, both validators and
   about 88 fixtures, so it lands on its own PR. Its "Lands with ADR-0009" line no longer holds.

### Security: what `vis: []` means (checked 2026-10-07)
**EV-13 does not define it.** The PRD's EV-13 (`docs/prd/tilo-prd-v2.md` line 219) is a metric,
"Autopilot draft acceptance", and says nothing about visibility. The contract rule EV-13
(`contracts/event.rules.md` line 24) ties a list to the event's district; before this amendment it
said nothing about an empty list. The meaning comes from the spec's redaction model:

- PRD 9.3 (line 710): `vis` is "district ids or `"all"`", the "Server-side redaction scope".
- PRD 10.1 (line 805): the Owner sees everything. A Team Lead sees their districts plus summaries,
  an Approver their cards plus context, a Viewer the shared scope. Line 807: "Server-side
  redaction uses the event `vis` field".
- PRD 15.3 (lines 1241, 1242 and 1247): `worlds/{world}/events/{seq}` is the "full stream (owner)",
  `views/{scope}/events/{seq}` is the "redacted stream per scope", and the harness writes each
  view itself.
- PE-12 (`contracts/people.rules.md` line 39): Desk and meeting worlds "have no Viewer, Approver or
  Team Lead scope".

So an empty list names no scope. The event goes into no view, and only the world's owner reads it.
That excludes everyone else, **including other members of the same world**: a Team Lead, Approver or
Viewer of that world gets nothing. Today's readers agree:
- `services/harness/src/tilo_harness/views.py` line 26: the shared view needs `"all"`, and a district
  view needs `"all"` or its own district in the list. `[]` is in neither.
- `services/api/src/tilo_api/redaction.py` lines 73 to 78 (`_visible`): true for the owner;
  otherwise a list is visible only if it names one of the principal's districts, which `[]` never
  does. So a member who passes `_require_member_world` (line 55) still gets nothing.
- `services/api/src/tilo_api/dev.py` line 101 refuses a `vis` that is None, not one that is falsy,
  so `[]` is never defaulted.

`[]` is the narrowest value and widens nobody's view. The one risk is a reader or writer that takes
an empty (falsy) `vis` to mean "not set" and fills in `"all"`, the leak BQ-73 guards against. Rule:
no reader or writer ever defaults or widens `[]`; only a missing or null `vis` is refused. A viewer
added later never sees the event, because views are written when the event is appended (ADR-0012
context). `vis` controls who can read an event, not what is authorised: an owner-only event
authorises nothing, and side effects still need `authz`, the outbox and the policy engine.

### Fixtures, types and tests
- `fixtures/events/invalid/vis_empty.json` (a `world.requested`, `district` null, `vis: []`) relied
  on `minItems`. It would now pass the schema, so the FR-WLD-03 and D-11 invalid-fixture tests
  would fail. It is renamed `invalid/vis_null.json` and now has `vis: null`, the BQ-73 workaround
  this ADR rejected, which the schema still refuses.
- New valid fixtures: `valid/work_item.created--desk_owner_only.json` and
  `valid/work_item.changed--desk_owner_only.json` (a confirm in the assignee's Desk world).
- New invalid fixtures: `invalid/vis_repeats_a_district.json` (`uniqueItems`) and
  `invalid/vis_list_names_all.json` (list items are district ids). New registry fixture:
  `registry/invalid/ev13_empty_vis_with_district.json`.
- Generated types: `EventDistrictList` loses `min_length=1` in Python, and in TypeScript changes
  from `[DistrictId, ...DistrictId[]]` to `DistrictId[]`. No hand-written code names it, and
  `apps/web/src` has no `vis[0]` (checked 2026-10-07). `DecisionDistrictList` keeps its minimum.
- Tests: `tests/contracts/test_ADR_0009_district_list_may_be_empty.py`.

### Follow-ups, not in this PR
- `services/api/src/tilo_api/cards.py` `_part` (lines 406 to 414) still writes `vis: None` plus
  `owner_only` for a card with no district (BQ-73). A builder moves it to `vis: []`; the tests that
  pin `vis is None` (listed above) need the test-writer.
- `services/api/src/tilo_api/desk.py` (line 3) writes Desk-world events with `vis: "all"`
  (BQ-PPL11B-11). PE-12 asks for `[]` once this lands. PPL-11c S5 does this for work items; the
  PPL-11b panel and nudge events need the same change.
- The primary fixtures `valid/work_item.created.json` and `valid/work_item.changed.json` keep
  `vis: "all"`. PE-12 would give them `[]`; that is a fixture-only change for the PR that follows.
- `docs/open-questions.md` BQ-73 and BQ-PPL11C-7 still say "needs contract change". Update them
  when this merges.
