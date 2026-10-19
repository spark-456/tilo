# FR-PA-08 people assistant STATUS and weekly summary: the interface these tests pin

Requirement (`docs/prd-addendum-people-agents.md` 3.2, Should, P5, depends on FR-PA-02): "`STATUS` gives one line per running
task and per item changed since yesterday; weekly summary from a template", acceptance "equals world and item state on 5
fixtures". Supplement 2026-10-05 3.1: STATUS is a panel question answered from the same read models (WhatsApp is out). Rules
that bind: FR-PA-11/13/17/19, PE-26..30, PE-12, HR-1, EFF-01. Open questions: `BQ-PPL11C-20` to `-24`. No contract change and
no new event type: the answers use `assistant.asked` and `assistant.replied`, `ui_action` `navigate` to `plate`.
Built on `API_PPL_11b.md` (`tilo_api.assistant`, `config/assistant.yaml`); read that first. Order of truth: `contracts/`, the PRD, this file.

## 0. Slices, files, gating

| Slice | Delivers | Tests (all names carry `FR_PA_08`) |
| --- | --- | --- |
| S1 STATUS | intent `status`: sections, window, caps, gating of the `done` lane | `test_FR_PA_08_s1_status.py` (strict xfail) |
| S2 weekly | intent `weekly`: five counts from the plate and the person's finished items | `test_FR_PA_08_s2_weekly.py` (strict xfail) |
| guards | older intents keep their words; other-person words decline first; failed/403/503; no clock read | `test_FR_PA_08_guards.py` (green today, never pending) |

`SLICE_PENDING` in `_fr_pa_08_lib.py` holds `test_FR_PA_08_s1_` and `test_FR_PA_08_s2_`; `conftest.py` marks them `xfail(strict)`. A
builder deletes its own entry in its PR (a green test with its entry left fails). See the real failures with `--runxfail`. Core-level
tests call `core.answer` through `_ppl11b_lib.run_answer` (signature unchanged); weekly and the route tests use `Rig`. Builder sketch,
about 150 lines: `assistant/status.py` (pure: window, sets, lines), a `status`/`weekly` block in `assistant.yaml` plus loader keys, parked-lane gating in `core._gated_rows`, the weekly read in `route._handle`.

## 1. Interface

No new route. Both are fact intents of `POST /v1/assistant/ask` (body, 200 shape, events, 403/415/413/422 as in 11b section 1), chosen
by the rules in `config/assistant.yaml` and also pickable by a model by id (`ModelDecision("intent", intent="status")`, then the same lines, `decided_by` model).

- `status` for: `Status`, `STATUS`, `Status update`, `Give me a status update`, `What is my status?`, `Can you give me my status please`.
- `weekly` for: `Weekly summary`, `Give me my weekly summary`, `Summary of my week`, `How was my week?`, `Week in review`.
- Unchanged (guards): `What is the status of my tasks?` and `How are my tasks going?` stay `tasks`; `What changed since yesterday?` and `What's new?`
  stay `changed` (the 24-hour rolling FR-PA-13 answer); `What is due this week?` stays `due_soon`; `... calendar this week?` stays `calendar_today`.
  Hint: drop `status` from `tasks.when`, order `tasks` before `status` before `changed`, then `weekly` after `due_soon`/`calendar_today`/`changed`.
- A question naming or implying another person (`Priya's status`, `her status update`, `how was her week`) is `other_person` before any lookup (existing rule).

## 2. Clock and time zone

`now` is `Ask.now` (the route's single `events.now()`); no other clock is read. The zone is the person's own record `time_zone`, passed as
`core.answer(time_zone=...)`; `None` or a name `zoneinfo` cannot load means UTC (as `facts._clock` does).
- `since` (STATUS): 00:00 of the previous local day, as an instant: `datetime.combine(local_date - 1 day, time.min, zone)` converted to UTC.
  A row counts when `since <= at <= now` (both inclusive, millisecond exact). So the window is 24 to 48 hours and moves at local midnight. Not "now minus 24 h".
- `week_start` (weekly): the same at `local_date - 6 days`: seven local days including today. A DST change inside the window moves the instant, never the date rule
  (fall back 2026-11-01 New York: since = 2026-11-01T04:00Z for now 2026-11-02T12:00Z; spring forward: since = 2026-03-08T05:00Z for now 2026-03-09T12:00Z).
- `plate["today"]` and `plate["as_of"]` are not read for this.

## 3. STATUS (`status`)

Source: the gated plate only (11b section 7 step 2, plus the `parked` lane gated the same way: a parked row the oracle refuses is dropped and logged `assistant.plate_row_refused <kind>`).
- **Running task**: a `rows` row with `ref.kind == "world"` and reason `run` or `blocked`. Line: `answer.lines[reason]` (`<title>: running`, `<title>: blocked`) plus `due_suffix`, `flagged_suffix`.
- **Changed since yesterday**: first the `rows` rows with `since <= at <= now` whose kind is not `world` and reason is not `calendar` (cards, work items, pins, mail), in plate order; then the
  `parked` rows of group `done` and kind `work_item` (PE-27: finished in the last 24 hours, so always a change), in parked order, line `"$label: done"` plus `flagged_suffix`.
  Snoozed and asked rows are not changes. A world row is listed once, as a task, never again as a change. One line per ref: the first occurrence wins, the `rows` copy beats the `parked` copy.
  `at` is the plate's stamp for the row (PE-29: creation, start, receipt or last pin change); the plate has no per-change time, see BQ-PPL11C-21.
- **Lines** (fixed words, in order): `Your tasks:` (no source), the task claim lines or `No task is running.`, `Changed since yesterday:` (no source), the change claim lines or `Nothing changed since yesterday.`.
  At most `answer.max_lines` (10) claim lines per section; if either section was cut, a last line `answer.more` and the offered `ui_action` `{"kind": "navigate", "route": "plate", "target": null}`.
  Nothing running and nothing changed: outcome `declined`, `decline` `empty`, one line `Nothing is running and nothing changed since yesterday.`, no sources (HR-1). Otherwise `answered`, `intent` `status`, `decided_by` rules.
- A claim line's label is the row `title` the plate already shows this person, else the existing `kind_labels`/`untitled`. No other text of a record is read. A title is data: it is substituted into
  a `string.Template` as a value and never parsed; `$`, `${x}`, `%s`, `{0}`, a header lookalike or an instruction changes no line, no source and no count.

## 4. Weekly summary (`weekly`)

Five counts, fixed words, no title anywhere: `Your week:` then `Done in the last 7 days: $n`, `Open work items: $n`, `Overdue: $n`, `Tasks in progress: $n`, `Waiting for you: $n`.
- **Done**: the person's own work items, read as `people.work_items.list(org, "owner", user)` (once per request, with the request's one `Directory`), each gated by the oracle as the person
  (`RefGate.allows`), whose `status` is `done` now and whose latest `history` entry with `change == "done"` has `week_start <= at <= now`. Distinct items: done, reopened, done again is one; reopened
  or dropped now is not counted; an edit after the done stamp does not matter; another person's item, another org's item and an unreadable record are never read or counted.
- **Open** = gated `rows` of kind `work_item`; **Overdue** = rows in group `overdue` (any kind); **Tasks in progress** = world rows reason `run` or `blocked`; **Waiting** = rows with reason `gate`, `consent`, `question`, `meeting_card`.
- Each count line cites one source because a `Line` has one: the first row of its category in plate order (Done: the latest finished item by done stamp, ties by id ascending). A zero count line has source `null`.
  All five zero: `declined`, `empty`, one line `Nothing to report for the last 7 days.`. When `plate["truncated"]` is true every plate count (not Done) gets a `+` suffix, even `0+`.
- Counts are not capped. Output is exactly six lines, `ui_action` null, `outcome` `answered`. Wording of the template lives in `config/assistant.yaml` and equals the strings in `_fr_pa_08_lib.TEXT`.

## 5. Ordering, caps, events

Plate order everywhere (PE-28), so web, digest and panel agree on ids (FR-PA-02). Sources: distinct, at most 20 (STATUS 10 + 10), equal to `assistant.replied` `data.sources`. The events are the two of 11b section 1,
summary `The assistant answered from <n> records.`, `credits` 0, `cost` zeros, `now` read once. Replay-only (NFR-24) changes nothing: both intents are rules. Nothing is written but the two events and the archive records;
the question and the answer text live only in the redacted archive (PE-16). Logs carry kinds and exception type names only. No animation: the panel renders the lines it already renders (HR-1).

## 6. Failure and privacy

- A plate source that raises, a plate that does not conform, or a `work_items.list` that raises (weekly) is outcome `failed` with `declines.failed`, status 200, no sources, never a partial answer (the panel's contract, 11b section 1 step 5/7; BQ-PPL11C-24).
  An unwired seam is 503 `not_configured`; an email-channel principal 403; both store nothing. (The plate route `GET /v1/plate` answers 503 for a failing source; the panel does not.)
- The person is the principal; role, world and districts are ignored (a Viewer principal gets the owner's body). No body, question, record or model reply names whose data is read (PE-26). Priya's plate is never built; every oracle request has `actor == u_sam`, `action == "read_full"`.
- Leaks (E-PRIV panel cases): the body, events, archive, logs and every `GenerateRequest` hold no id or title of a record the person may not read; a refused row never appears or is counted.

## 7. Deferred (do not build here)

Finished or failed runs (the plate holds only running and blocked ones; no completion stamp); meetings as changes (only `meeting_card` rows); a true "changed at" stamp (needs `changed_at` on `plate_row`: a contract change, ADR first); changes to snoozed or asked items;
a scheduled weekly push or email (FR-PA-05/06, the sweeper); per-day or per-team breakdowns; comparing weeks; a count of time saved (FR-PA-20); web UI beyond the existing panel; a real `PlateSources`/`PeopleStores` adapter (PPL-11c).
