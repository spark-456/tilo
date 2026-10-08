# FR-PA-10 people assistant: free-text updates reach the typed actions of FR-PA-16 (what these tests pin)

Requirement (`docs/prd-addendum-people-agents.md` 3.2, Could, P5, depends on FR-PA-14): "Free-text updates ("done", "move it to Friday") reach the
same typed actions as FR-PA-16 by the panel's rules first and the `assistant` role as fallback. A reassign is a request to the meeting Owner".
Acceptance: "30 phrases >= 90% parsed; a non-owner's phrase never changes state". Binds: PE-10, PE-15 (dates by code), PE-19, PE-11, PE-12, PE-21,
FR-PA-17/19, HR-1, EFF-01, SEC-01. Built on `API_PPL_11b.md` and `API_PPL_11c.md` (read them first). Open questions `BQ-PPL11C-26` to `-33`.
**Needs contract change (one, deferred, section 6):** `ui_action` has no reopen, not-mine or put-back kind. Nothing else changes.

## 0. Slices and gating
| Slice | Delivers | Tests (all names carry `FR_PA_10`) |
| --- | --- | --- |
| s1 rules | `assistant/updates.py` (grammar, target, day, vet), `declines` keys, core order | `test_FR_PA_10_s1_rules.py` (strict xfail) |
| s2 fallback | model `update` choice: `model.parse_decision`, prompt, core vet | `test_FR_PA_10_s2_fallback.py` (strict xfail) |
| s3 follow-through | nothing new in src: proves the proposal drives the existing routes | `test_FR_PA_10_s3_follow_through.py` (strict xfail; needs s1) |
| guards | green today: no new route, no writer import, closed set, hostile text, fixture shape | `test_FR_PA_10_guards.py` (never pending) |
`SLICE_PENDING` in `_fr_pa_10_lib.py` holds `s1 s2 s3`; delete your entry in your PR (a green test with its entry left fails). `--runxfail` shows the failures.
Fixture `fixtures/assistant/updates.json`: 30 phrases (26 by rules, 4 by recorded model replies), 12 hand-off phrases. No live recording exists; re-record by hand with LIVE set by the user.

## 1. Interface (no new route, no new event, response keys unchanged)
`POST /v1/assistant/ask` (body, 200 shape, events as 11b section 1). An update the person may carry out is a **proposal**: `outcome` `answered`, one line that names the
item (cleaned title, else `untitled`; a flagged title is withheld, PE-21) and, for a snooze, the **local** `YYYY-MM-DD`; `sources` = that one work item;
`ui_action` = `{"kind":"mark_done","work_item_id"}` or `{"kind":"snooze","work_item_id","until"}` (validates against `ui_action.schema.json`); `cost.model_calls` 0 (rules) or 1.
**The ask route writes nothing**: no people store call, no `work_item.*` event, only `assistant.asked` and `assistant.replied` (ids and enums, no title, phrase or date text, PE-12).
Confirmation (PE-10): `decided_by` `model` means the web must show a confirm chip before it calls the route; `decided_by` `rules` may run at once (it is the same call as the button).

## 2. Rule grammar (after the panel's normalisation: NFKC, control and format characters removed, casefold, leading fillers dropped, trailing `.!` ignored)
A rule reads the **whole** utterance or nothing; text before/after a verb, a second verb, an id or a delimiter is no hit. Order in `core.answer`: other-person decline, **update rules**,
navigation, facts, then the model. (Update first: facts words such as `wait` must not capture an update.)
| Utterance (forms) | Action | Params |
| --- | --- | --- |
| `done`, `all done`, `finished`, `it is done`, `it's done`, `that is done`, `mark it/this/that (as) done`, `i am done (with it)` | `mark_done` | target |
| `done with <title>`, `finished <title>`, `mark <title> (as) done` | `mark_done` | target by title |
| `snooze`, `postpone`, `defer`, `push`, `move`, `reschedule` + (`it`/`this`/`that`/`<title>`) + (`to`/`until`/`till`/`for`/`on` `<day phrase>` or `in ...`) | `snooze` | target, `until` |
| `reopen`, `re-open it`, `put it back (on my plate)`, `unsnooze it`, `not mine`, `this/it is not mine`, `reassign it/this` | hand-off (section 6) | selected item |
`<title>` may carry `the` and a trailing `task` or `item`. A bare `snooze` means `tomorrow` (BQ-PPL11C-27). "move it to <day>" is a snooze (BQ-PPL11C-26).

## 3. Target
1. A title: its words minus `words.title_skip` must be a subset of exactly one of the person's gated **work_item rows** (the 11b/nav rule, words of 3+ letters): that item, even when another is selected.
   Two or more matches: question `which_item`. No match: the rules cannot decide, so the model is asked (section 5).
2. No title or a pronoun: the selected record, if the gate admits it and it is a work item. Anything else (none, a world, pin, card, meeting, Priya's id, another org's id, an id that exists nowhere,
   an item the person may not read in full such as one they only assigned) is the one question `which_item`: byte-identical answers, no model call, no write (PE-11).
3. Vet (rules and model alike), on the **current stored record**, not the plate row: `tilo_people.access.decide` called through the module (so `AccessSpy` sees it) as the signed-in person,
   `mark_done` for a done, `edit` for a snooze, with the source meeting loaded as `people_access.read_as` does (PE-19; a Tilo-made item needs it). Refused (done item, stale plate, not the owner,
   not `open`): `update_refused`, one text for every reason. The actor is only ever the principal.

## 4. Dates and the new `declines` keys (`config/assistant.yaml`, loader `DECLINE_KEYS`; texts are the builder's; tests read them from the file)
`resolve_due(phrase, meeting_at=Ask.now, time_zone=<person.time_zone>)` (PE-15), never a model, never the wall clock (`rig.now_calls == 1`). `until` = **09:00 local**
(`config/personal.yaml working_window.start`) on the resolved day, as `YYYY-MM-DDTHH:MM:SS.000Z`. The phrase handed over is what follows the preposition; `in 3 days` is a phrase.
| Situation | Answer |
| --- | --- |
| phrase not resolved (`ambiguous`, `not_understood`, `too_long`, `out_of_range`, ...): "friday" on a Friday there, "next friday", "next week", "the weekend", "yesterday" | `declined`, `which_day`, no model |
| resolved but `until` not in (now, now + 30 days] (equal to now is too early; exactly 30 days is allowed; the route's own window) | `declined`, `snooze_range` |
| unusable zone | UTC, as `facts._clock` |
Other new keys: `which_item`, `update_refused`. All `declined` with `decided_by` rules, `ui_action` null, no source.

## 5. The fallback contract (`assistant` role, config only; FR-PA-19 caps and cache as 11b)
Asked **once** and only when the rules cannot decide (nothing matched, or a title matched nothing). Not asked for a clear update, an ambiguous title or a day code cannot resolve.
The reply is exactly `{"choice":"update","kind":"mark_done","work_item_id":ID}` or `{"choice":"update","kind":"snooze","work_item_id":ID,"when":PHRASE}` (exact keys and JSON types;
the model never gives a timestamp; `when` is run through section 4). Anything else, or any failed vet (id not in the shown menu, not the person's own open item, bad day, a kind such as
reopen/send/tag, an extra key), is `dropped` (fixed text, `decided_by` model). `parse_decision` and the prompt gain this shape; the prompt offers only the two kinds.
A valid reply gives the same proposal with `decided_by: "model"`, actor `A_assistant`, `trace.model_role` `assistant`. Unavailable, budget or flagged: rules still answer; the rest is `rules_only`, `budget`, `flagged`.

## 6. Hand-off and the contract gap (needs contract change, deferred)
Reopen, put back and not mine (the PRD's "reassign is a request to the meeting Owner") are recognised by rules, never sent to the model, never written, and answered as `navigated`,
`{"kind":"navigate","route":"plate","target":{"kind":"work_item","id"}}` for the selected item. A model reply naming them is dropped. Real actions need `ui_action` kinds `reopen`,
`not_mine`, `put_back` (a minor contract version, architect, then FR-PA-10b); the routes already exist (`POST /v1/work-items/{id}/reopen|not-mine|put-back`).

## 7. Follow-through (s3)
The web posts the same route as the button: `POST /v1/work-items/{id}/done {}` or `.../snooze {"until"}`. Same `check_write`, compare-and-set, one `work_item.changed` in the owner's Desk world, same
60 POSTs a minute per principal (S4; asking uses none of it), same 404 for a stale or foreign id. Idempotency-Key exists only on the four creates; a repeated confirm is refused by state.

## 8. Deferred, errors, overlap
Errors as 11b (403 channel, 413, 415, 422 incl. 500+ characters, 503 `not_configured`). Deferred: reassign to a named person, edit due or title by phrase, tag/untag by phrase, `remind me` (FR-PA-05/15
nudges), other languages (English only), several items in one phrase, parked (snoozed/asked/done) items by title. No overlap with FR-PA-05/06/15 (no clock job, no digest, no nudge); FR-PA-08 adds
intents after this order (`status`, `weekly`) and must keep the update rules first.
