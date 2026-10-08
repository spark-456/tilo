# MF-02 Personal pinboards (draft, waiting for your OK)

**Status: proposal.** Builds on MF-01 (same pin model and commands). Nothing is built.

## Goal
Each participant can keep their own private list during the meeting (their follow-ups, things to check) without it cluttering the team board.

## The constraint that shapes this
Meet's chat is one group chat: the bot cannot send a private message, and everything it says aloud is heard by everyone. So **the bot never reads a personal pin aloud or posts its text**. Personal boards are written to files and delivered after the meeting.

## Behaviour
- **Add:** "Tilo, pin for me: check the vendor quote", typed `pin me: check the vendor quote`, or `pin for Priya: ...` (any present participant). Owner is the speaker's name as Meet shows it (chat) or as the speaker label gives it (voice); an ambiguous or unknown speaker gets "I couldn't tell who that is for." and nothing is stored.
- **Confirm:** "Pinned for Sam." (no text, no number). Spoken and in chat.
- **Ask:** "what is pinned for me?" is answered with the count only: "You have 2 personal pins; they are in your file after the meeting." The text is not repeated.
- **Remove:** `unpin me 2` by the owner only.
- Personal pins are separate from the team board and never appear in `summary.md`'s team section or in `state.json`'s `pinboard`.

## Outputs
`pins/<name>.md` per person in `out/<run>/` (name made filesystem-safe). Nothing else. The folder is local and gitignored like the rest of `out/`.

## Privacy and disclosure
A personal pin is meeting content written to a local file, like the transcript. Because it is private in intent, it is **never sent to the model** except to answer the owner's own request (this spec proposes: not at all in v1, since the count answer needs no model). The intro line gains "personal pins are saved to private files" while the feature is on.

## Acceptance tests (offline)
1. `pin me: X` from Sam creates `pins/Sam.md` with X and answers "Pinned for Sam." with no text.
2. `pin for Priya: X` from Sam stores it for Priya, not Sam.
3. "What is pinned for me?" answers with the count and never the text, in voice and chat.
4. A personal pin never appears in the model prompt, `state.json`, `summary.md`, `latency.jsonl` or `turns.jsonl` (text is redacted in the trace for these turns).
5. `unpin me 1` by another person is refused with "Only the owner can remove that."
6. Unknown speaker → the "couldn't tell" line and no file.

## Proposed tickets
| Id | Ticket | Size |
|---|---|---|
| MF-02a | Personal board store, parsing (`pin me`, `pin for`, `unpin me`), files, redaction in the trace. Tests 1, 2, 4, 5, 6. | ~250 |
| MF-02b | Wiring and the count answer. Test 3. | ~120 |

## Open questions
1. Is "private until after the meeting" right, given the bot cannot DM? Alternative: never store personal pins at all and only send them by email later (needs an outbound channel, out of scope).
2. Should the pins be handed to people after the meeting (how? there is no email or DM path today), or is the file enough for now?
3. Can one person pin for another, or only for themselves?
