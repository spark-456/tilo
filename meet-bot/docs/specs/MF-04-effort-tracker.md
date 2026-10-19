# MF-04 Effort tracker (draft, waiting for your OK)

**Status: proposal, and the term is ambiguous, so this needs your decision before any build.** "Effort tracker" can mean at least two different things; both are small and independent.

## Reading A: effort estimates on action items
People say "that's about two days" or "three points". The bot records an estimate against the action item (and its owner), and totals it.
- **Capture:** from the analysis loop (new optional `effort` field on an action item, text as said: "2 days", "3 points") and explicitly: `effort pricing page = 2d`.
- **Normalise:** hours and days only (`2d` = 16 h; configurable working day). Points and T-shirt sizes are kept as given and not converted.
- **Ask:** "how much effort is on Priya?" answers with the sum in hours and the count of unestimated items, locally (no model).
- **Output:** `effort.md` (per item and per owner, unestimated items listed) and an "Effort" section in `summary.md`.

## Reading B: where the meeting's time went
Planned versus actual time per agenda item, and optionally talk time per person.
- **Actual time per item:** derived from the agenda statuses the brain already tracks (`in_progress` to `covered`) and their timestamps, with the planned minutes from the agenda.
- **Talk time per person:** seconds of transcript per speaker (an approximation from utterance spans, stated as such).
- **Output:** `time.md` (table planned vs actual with the difference) and a "Time" section in `summary.md`. No live nudges beyond the existing time warning.
- **Privacy note:** talk time per person is sensitive in some teams; proposed off by default (`TRACK_TALK_TIME=1`) and named in the intro line when on.

## Acceptance tests (offline)
Reading A: (1) an estimate in chat attaches to the matching item and owner; (2) `2d` and `3 days` both normalise to 16 h and "3 points" is kept as given; (3) the owner total counts unestimated items; (4) "how much effort is on Priya?" needs no model.
Reading B: (5) planned versus actual is exact on a fake clock replay; (6) items never started show 0 and are flagged; (7) talk time is absent unless the flag is on.

## Proposed tickets (after you pick)
| Id | Ticket | Size |
|---|---|---|
| MF-04a | Reading A: field, parsing, normalisation, totals, outputs. Tests 1 to 3. | ~250 |
| MF-04b | Reading A wiring and the local answer. Test 4. | ~120 |
| MF-04c | Reading B: timing from agenda status changes, `time.md`, summary section. Tests 5 to 7. | ~220 |

## Open questions
1. **Which reading do you mean, A, B or both?** This decides everything above.
2. For A: hours and days, or story points? Is the working day 8 hours?
3. For B: is talk time per person wanted at all?
