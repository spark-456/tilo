# FR-CAL-07 part (a), the assistant panel half: "what is on my calendar today" and "what should I prepare for the 3pm" (what these tests pin)

Requirement (`docs/prd-addendum-people-agents.md`, Should, P5/P6, depends on FR-PA-13 and FR-CAL-02): "Panel and rescheduling. The panel answers 'what is on my
calendar today', 'what should I prepare for the 3pm' and navigates to the entry. A mail asking to move a meeting proposes times that are actually free from
the free/busy read (FR-CON-14 acceptance)". Part (a) is the panel only; the mail half is part (b) and has no test here. Rules that bind: FR-PA-11/13/14/17/19,
FR-CAL-03/05/06, PE-04, PE-07, PE-12, PE-19, PE-21, ADR-0020 (no quote text in an archive, event, log or model prompt), ADR-0021, HR-1, EFF-01.
Built on `API_PPL_11b.md` (`tilo_api.assistant`, `config/assistant.yaml`) and `API_FR_PA_08.md` (the pattern); read those first.
**No contract change, no new event type, no new route:** `navigate` to route `calendar` with target kind `calendar_entry` is already in `ui_action.schema.json`,
`navigation.ROUTE_TARGETS` and `route_for`. Both answers use `assistant.asked` and `assistant.replied`. Order of truth: `contracts/`, the PRD, this file.

## 0. Slices, files, gating
| File | Delivers | Status |
| --- | --- | --- |
| `test_FR_CAL_07a_today.py` | `calendar_today` amended: own accepted entries only, offer to open the entry when exactly one | strict xfail |
| `test_FR_CAL_07a_prepare.py` | new fact intent `calendar_prepare`: time resolution, template, links, decline, model-by-id, config | strict xfail |
| `test_FR_CAL_07a_privacy.py` | route body and events, replay-only, other people, leaks, redaction, hostile text and CPU bound | strict xfail |
| `test_FR_CAL_07a_guards.py` | fixtures and oracles match this file; older intents unchanged; failure paths; no store write in the package | green today, never pending |

`SLICE_PENDING` in `_fr_cal_07a_lib.py` holds the first three file names; `conftest.py` marks them `xfail(strict)`. The builder deletes the entries in his PR (a green test
with its entry left fails). See the real failures with `--runxfail`. One builder, about 250 lines: a `calendar_prepare` block in `assistant.yaml` plus loader keys
(`answer.prepare.*`, `declines.which_entry`, a `report`-style kind), `assistant/calendar.py` (pure: time parse, entry pick, lines), the own-and-accepted filter in `core`/`facts`.

## 1. Amends a pinned PPL-11b test (the builder does this, in the same PR)
A13-1 questions 11 and 12 (`What is on my calendar today?`, `What's my schedule for today?`) run on plate S1, which holds exactly one calendar row (`ce_plan1`). Under this ticket the answer
also offers `ui_action` `{"kind":"navigate","route":"calendar","target":{"kind":"calendar_entry","id":"ce_plan1"}}`, so `_ppl11b_lib.expected_facts` must return that `ui_action` for
`calendar_today` when exactly one row is listed (and drop proposed and other people's rows). Nothing else in PPL-11b, FR-PA-08 or FR-PA-10 changes; run `-k "PPL_11b or FR_PA_08 or FR_PA_10"`.

## 2. `calendar_today` (existing intent, amended)
Source: the gated plate's rows of reason `calendar` (ids and order stay the plate's, ADR-0021). A row is **listed** only when the entry the oracle shows the person (`RefGate.record`) has
`owner == the signed-in person` and `state == "accepted"` (for a Tilo-made entry that means `confirmed_by` is set, which the oracle already enforces). So a proposed entry, an entry of another
person (a teammate's entry shared with the team is readable but is not on this calendar, PE-04) and an entry the gate refuses are dropped, whatever the plate says.
- Lines: unchanged words (`facts[calendar_today].header`, `answer.lines.calendar` = `$time $label`, `flagged_suffix`); `$time` is the start in the person's `time_zone`, UTC when unknown; plate order (start ascending).
- `ui_action`: exactly one listed entry: `navigate` to route `calendar`, target that entry (as `route_for` builds it, so it validates against `ui_action.schema.json`). Two or more, or none: `null`.
- Nothing listed: outcome `declined`, decline `empty`, the intent's `empty` text, no source (HR-1). `decided_by` rules, no model call. Unchanged: `This week?` stays `calendar_today`.

## 3. `calendar_prepare` (new fact intent)
- **Config** (`config/assistant.yaml`): fact id `calendar_prepare`, `when: [[prepare, prep, preparation]]`, placed before `waiting` (whose word `need` is in "what do I need to prepare") and before
  `calendar_today` (whose word `calendar` is in "... on my calendar"). Fixed words, exactly as `_fr_cal_07a_lib.TEXT`: `answer.prepare.{header,entry,entry_open,attendees,meeting,item,nothing}` and
  `declines.which_entry`. Placeholders `$label $start $end $n` only; a title is a value and is never parsed as a template (hostile titles test). A model may pick it by id (`ModelDecision("intent", intent="calendar_prepare")`).
- **The time**: after the panel's normalisation (NFKC, control and format characters removed, casefold) the question names **exactly one distinct time of day**: `H`, `H:MM` with `am` or `pm` attached
  or as the next word (`3pm`, `3 pm`, `3:30 PM`, hour 1 to 12, minute 00 to 59; `12pm` is 12:00, `12am` is 00:00), or `H:MM`/`HH:MM` with no suffix as a 24-hour time (`15:30`, `0:30`, hour 0 to 23). A bare
  number (`meeting 3`), an invalid time (`13pm`, `0pm`, `3:75pm`, `25:00`), no time, or two different times (`the 3pm and the 5pm`) are no time: decline `which_entry`. The same time twice is one time.
  `tomorrow` or `yesterday` anywhere in the question is `which_entry` too (only today's entries are prepared for; BQ-CAL07-3).
- **The entry**: among the listed entries (section 2 rules: own, accepted, the gate admits) those whose stored `start`, in the person's time zone, is on the local date of `Ask.now` and equals the time to the
  minute (the stored start is checked, not only the plate row). Exactly one: answer. None or two or more: outcome `declined`, decline `which_entry`, one line `declines.which_entry`, no source, `ui_action` null.
  Which of these it is depends only on the question and the person's own records, never on whether someone else's entry exists (FR-PA-17). No candidate title is offered.
- **Lines** (first four are the entry's own fields; the rest are links the person may read):
  1. `To prepare:` (no source)
  2. `$label at $start to $end` (`$label at $start` when `end` is null; the flagged suffix when `flagged`), source the entry. Times are `HH:MM` in the person's zone.
  3. `Other attendees: $n`, source the entry, only when `attendee_count > 0`.
  4. `Meeting: $label`, source the meeting, when the entry is Tilo-made from a meeting, the meeting is `entry.source.ref` up to `#`, and the oracle admits it for the person (`RefGate.record`).
  5. `Action item: $label` plus the existing `due_suffix` and `flagged_suffix`, source the work item, when `entry.source.ref` holds `#` and the oracle admits the one work item of the entry's owner whose `source.ref`
     equals it (the same link `read_as` loads). Another person's meeting is never named, however it is linked.
  6. `Nothing else is linked to it.` (no source) instead of 4 and 5 when neither is listed.
  Outcome `answered`, intent `calendar_prepare`, `decided_by` rules (model when picked by id), sources distinct. `ui_action` is always the `navigate` to the entry (never the meeting).
- **No quote text.** ADR-0020 forbids a transcript quote in the raw archive, events, logs and model prompts, and the panel stores its answer text in the archive, so the answer cites the meeting and the action item
  by title and record only; the evidence quote stays on the meeting and work-item screens (BQ-CAL07-2).

## 4. Model fallback
Unchanged contract (FR-PA-14): a question no rule reads may be sent to the `assistant` role, which can only pick a fact intent by id or propose a navigate that code vets. `calendar_prepare` joins the menu's intent ids.
Picked by id, code resolves the time from the same question text; no time in it is the `which_entry` decline (`decided_by` model). Replay-only mode answers both calendar questions (rules) and declines the rest.

## 5. Cost, privacy, bounds (every one is a test)
- Rules answer: 0 model calls, `cost` zeros, nothing cached, one `events.now()` read, one plate build, the two existing events, summary `The assistant answered from <n> records.`, `credits` 0.
- The person is the principal; every oracle request has `actor == u_sam` and `action == "read_full"`. Priya's plate is never built; her entries, titles and meetings appear nowhere (body, events, parts, logs, archive),
  and an entry or meeting that is not readable by the person is dropped before the answer, so the reply is the same as if it did not exist.
- Events and logs carry ids and counts only (PE-12); the answer text lives only in the redacted raw archive (a secret in a title is `[REDACTED]` there). The question is never echoed in an answer.
- Nothing is written: no people store call other than reads, no `calendar.*` event, no outbox entry (static guard: no `create`/`delete`/store `replace` call in `tilo_api/assistant`).
- Hostile input is bounded: the question is normalised once (`question_key`), titles at most once each, no per-token quadratic work; a 2000-character NFKC-amplifying question, a flood of times or of `in` words, and 150
  entries with such titles answer in under 10 s with at most `1 + rows` normalisations and no model call.

## 6. Deferred (do not build here)
Part (b): a mail asking to move a meeting proposes times that are free from the free/busy read (FR-CON-14 acceptance), and the calendar write behind it (FR-CAL-04, FR-PA-16). Resolving an entry by title or by the
selected record ("prepare for this"); all-day entries; days other than today; a model-written preparation line; quote text; free/busy of teammates in the panel (FR-CAL-06 stays the Calendar screen's); web UI beyond the
existing panel (it already renders `ui_action` `navigate`).
