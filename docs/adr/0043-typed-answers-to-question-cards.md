# ADR-0043: A person may answer a question card in their own words

- Status: **Accepted** (15 Oct 2026). The user decided it on 15 Oct at 01:45 IST ("yes, typed answers"). The
  contract change is additive: `events/data/question.answered.schema.json` goes from 1.1.0 to 1.2.0 and every existing
  fixture stays valid. The code (the answer route, the web card and the waiting unit) is the builder's ticket on
  `fix/OWN-ANSWER`. (Next free number on `origin/main`, every `origin/*` branch and every open PR at 15 Oct.)
- Deciders: user (typed answers allowed), architect (contract shape)
- Requirement: FR-HIL-10; PRD 9.5, 10.2, 10.6; FR-AGT-07 (Decisions); SEC-04; ADR-0011 (absent, never null)
- Questions: new BQ-OWNANS-1 to BQ-OWNANS-3 in `docs/open-questions.md`.

## Context
1. **What went wrong.** In a live run for a trip from Chennai to Gokarna, a mid-run question card offered only two
   options: the model's guess, "Europe", and "Ask me later". Neither was the right answer, and the person had no
   way to give it. The run could only go on with a wrong destination or wait.
2. **What the contracts allow today.** `question.answered` data holds `answered_by` and `decision_id` only. The
   chosen option is not event data. It travels as scope in the part the API hands the writer (BQ-207, BQ-215).
   The card answer request body is `_AnswerBody` in `services/api/src/tilo_api/cards.py`, which is code, not a
   contract, and its `option` is required. A Decision can already hold a typed answer (`decision.schema.json`:
   `answer` is 1 to 2,000 characters, and `option` is null for a typed answer). The MCP tool `answer_card`
   (`mcp_tools.schema.json`, ADR-0031, Proposed, not built) takes an option only. Gate and consent answers are closed
   documents (`approval.resolved` option is approve, edit or hold; CR-07, CR-13).

## Decision
1. **`text` on `question.answered` (1.2.0).** An optional string of 1 to 300 characters holding at least one
   character that is not white space (`pattern` `\S`, which reads the same in python-jsonschema, pydantic and
   ECMA-262 with and without the `u` flag). It is present only when the answer was typed, and absent otherwise, never
   null (ADR-0011). It is allowed when `answered_by` is `person` or `team_lead`. It is refused when `answered_by` is
   `default` (a timeout applies the card's `safe_default`, always an option) or `decision` (the answer stays in the
   Decision that `decision_id` cites). The 300-character cap is the user's.
2. **One answer, one form.** Each answer is either an option or typed text, never both and never neither. The event
   cannot check this, because the option is scope, not event data (BQ-207). So the route checks it on the request
   (BQ-OWNANS-1). In the event, `text` present means a typed answer, and `text` absent means an option.
3. **Question cards only.** Only a card of kind `needs_you` takes typed text. Gate, consent and meeting cards keep
   their fixed options. `approval.resolved` and `connection.consented` stay closed: the invalid fixture
   `fixtures/events/invalid/approval_resolved_with_typed_text.json` shows that a gate answer with text fails. A typed
   answer authorises nothing. It never opens a gate, grants a connection or counts as an owner's L2 instruction
   (OB-01 reads `world.requested` only), and a model never decides authorisation.
4. **Where the text comes from.** Text comes from a person's answer on tilo-api's card answer route only. It never
   comes from a channel message: an email reply's body stays in the raw archive (event.rules.md, payloads). Payloads
   never carry credentials, so the writer runs the secret redactor on the text before the event is written
   (BQ-OWNANS-3).
5. **The card answer request body has no contract**, so nothing in `contracts/` changes for it. The builder adds an
   optional `text` to `_AnswerBody` with the same bounds. A request carrying both or neither, or carrying text for a
   non-question card, is refused with a 400 before the store writes anything (the reason name is the builder's). The
   MCP `answer_card_in` stays option-only (BQ-OWNANS-2).
6. **Decisions.** Where a typed answer is kept as a Decision (a Team Lead's answer, FR-AGT-07), the Decision gets
   `answer` = the text and `option` = null. `decision.schema.json` already allows this, so it does not change.
7. **The registry does not change.** The Story line and the Trace row still show `answered_by`, so
   `events/registry.yaml` and `apps/web/src/world/registry.generated.ts` keep their version.

## Consequences
- The change is an additive minor version. The generated `QuestionAnsweredData` gains an optional `text` in
  `packages/contracts-py` and `packages/contracts-ts`. The generated Python model drops the if/then rules, as for every
  contract, so the writer validates against the JSON Schema. API tests that pin `data == {"answered_by": "person"}`
  stay true for option answers.
- New fixtures: two valid events (`question.answered--typed_by_person.json` and
  `question.answered--typed_by_team_lead_300_characters.json`) and eight invalid ones (empty, over 300 characters,
  white space only, null, not a string, typed text on a default answer, typed text on a decision answer, and typed
  text on a gate answer).
- **For the builder (`fix/OWN-ANSWER`).** (a) `CardStore.answer` puts `text` in the `question.answered` data and keeps
  the option in scope. It adds the text to the retry key `who`, so a resend after a failed write is recognised, and a
  different text under the same event id raises `AlreadyCommitted` instead of being silently deduplicated. This closes
  BQ-215's gap for typed answers. (b) The waiting unit's `Answer` carries the text, and the agent reads it as the
  person's answer to that one question: data, never an instruction to change tools, recipients or authority.
  (c) The web card offers a text box on question cards only. (d) The `summary` shown with the event is written by
  the writer ("You answered in your own words."), never by a model.
- A security review of the route, the redaction step and the screen question (BQ-OWNANS-3) is needed before the
  builder's change merges, because the typed text reaches a model.
