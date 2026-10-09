# MF-03 Responsibilities, who owns what (draft, waiting for your OK)

**Status: proposal.** Nothing is built. Today the bot already tracks action items with an owner and a due date (from the analysis loop), nudges once when an owner or date is missing, and answers "who owns X?" through the model. This spec makes ownership explicit, correct and durable for the meeting.

## Goal
A reliable "who owns what" table for the meeting: anyone can assign, reassign or ask, the answer is instant, and the table is in the outputs.

## Behaviour
- **Assign:** "Tilo, Priya owns the pricing page", typed `assign pricing page to Priya` or `owner: pricing page = Priya`. The owner must be a present participant or a name already heard; otherwise the bot asks once in chat: "I don't know a Priya here. Who is that?" and does not assign.
- **Reassign:** the same command replaces the owner and says so: "Pricing page: Priya (was Sam)."
- **Ask:** "who owns the pricing page?" and "what does Priya own?" are answered locally (no model), by voice and chat. Unknown: "Nobody owns that yet."
- **Model-found owners stay suggestions:** an owner the analysis loop infers from conversation is recorded as `inferred`; an explicit command is `confirmed` and wins. The existing "who owns X and by when?" nudge still fires for items with no owner at all, once.
- Areas are free text matched loosely (same 0.8 similarity the agenda items use). An area that matches an action item links to it and fills its `owner`.

## Outputs
`responsibilities.md` (table: area, owner, status confirmed or inferred, due, set by, time) rewritten on change; `state.json` gains `responsibilities: [...]`; `summary.md` gets an "Owners" section with unowned items listed separately.

## Acceptance tests (offline)
1. `assign X to Priya` by Sam records Priya as confirmed owner of X and posts one receipt line.
2. A second assign changes the owner and the receipt names the previous owner.
3. "Who owns X?" and "What does Priya own?" answer with no model call; a missing area says "Nobody owns that yet."
4. An unknown name gets the clarifying question and no assignment.
5. An inferred owner never overwrites a confirmed one; a confirmed one overwrites an inferred one.
6. The three outputs agree after a scripted replay; an item with no owner is listed under "Unowned".

## Proposed tickets
| Id | Ticket | Size |
|---|---|---|
| MF-03a | `bot/owners.py`: table, commands (assign, reassign, query), confirmed vs inferred merge with the brain's action items, outputs. Tests 1, 2, 5, 6. | ~280 |
| MF-03b | Wiring: commands ahead of the question path, local answers, unknown-name question. Tests 3, 4. | ~150 |

## Open questions
1. Must the owner be present in the meeting, or may it be any name (for example a teammate who is absent)?
2. Should responsibilities carry over into the next meeting? (Proposed: no, v1 is per meeting.)
