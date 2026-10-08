# Skill From Description (`skill-from-description`)

## When to use
Use this skill on the **Teach Tilo -> Describe it** path (`FR-SKL-01`, `FR-SKL-02`) when a user describes a repeated workflow in plain words and Tilo must turn that description into a structured, human-editable skill draft before saving or dry-running it.

## Steps
1. **Segment the description into grounded action clauses**: Extract only the actions explicitly stated by the user, preserving their chronological order. Do not add setup, cleanup, notification, or logging steps that the user did not ask for.
2. **Map each clause to `(verb, object, tool)`**:
   - Normalize `verb` to a clear base action verb (`read`, `summarise`, `draft`, `compile`, `send`, `pay`, `delete`, `share`, `book`, etc.).
   - Keep `object` grounded in the exact nouns and qualifiers from the user's description.
   - Bind `tool` strictly to one of the user's `connected_tools`.
3. **Enforce the `"ask me first"` safety gate (`ask_me_first`)**:
   - Any step whose verb or action **sends**, **pays**, **deletes**, **shares**, or **books** (`send`, `pay`, `delete`, `share`, `book`) **must** set `ask_me_first: true` (`FR-SKL-02`). It must never be `false`.
   - Purely internal read, search, summarise, or draft steps set `ask_me_first: false`.
4. **Check for material ambiguity (`clarifying_question`)**:
   - If a required target, recipient, channel, folder, or threshold is missing or underspecified, emit **exactly one** concise clarifying question ending with `?`.
   - If the description already specifies what to act on and where, set `clarifying_question: null`.
5. **Parse `trigger` and `scope`**:
   - Set `trigger.kind` to `"schedule"` (with `cadence` in `daily | weekly | monthly`) when the description states a recurring schedule, `"event"` (with `event`) when triggered by an incoming event, or `"on_request"` otherwise.
   - Set `scope` to `"team"` when the description explicitly targets the user's team or shared team workflow, and `"just_me"` otherwise.

## Quality bar
- **Zero invented steps**: Every step in `steps` corresponds 1-to-1 with an explicit action in `description` and shares lexical grounding with the input text.
- **Strict safety defaults**: Every `send`, `pay`, `delete`, `share`, or `book` step has `ask_me_first: true`.
- **Single-question discipline**: Never ask multiple questions at once; emit either `null` (when clear) or a single question string containing exactly one `?`.

## Checklist
- [ ] Every step `tool` is present in `connected_tools`.
- [ ] Every step `object` uses terms grounded in `description` (no hallucinated tables, channels, or side effects).
- [ ] Every `send`, `pay`, `delete`, `share`, or `book` step has `ask_me_first: true`.
- [ ] `clarifying_question` is `null` for unambiguous inputs and a single `?`-terminated question for ambiguous inputs.
- [ ] `trigger` and `scope` match the cadence and audience stated in `description`.

## Pitfalls
- **Inventing helpful follow-ups**: Adding an unrequested "send confirmation email" or "delete temporary file" step violates `FR-SKL-01` and `FR-SKL-02`.
- **Leaving `ask_me_first: false` on external side effects**: Steps that send messages, pay invoices, delete records, share documents, or book calendar slots must always default to `ask_me_first: true`.
- **Compound clarifying questions**: Combining two questions into one string slows down the card creation flow; ask only the single highest-impact question.
