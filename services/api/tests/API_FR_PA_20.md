# FR-PA-20 effort tracker, API half: the interface these tests pin

Requirement (`docs/prd-addendum-people-agents.md`, decision D-4, Should, P8, depends on FR-MTR-05): "Effort tracker: Tilo's own
effort only, credits and time-saved estimate per meeting and per task from P8 (14.4), shown on S-26 and the world HUD. No human
time tracking." Acceptance: "Numbers equal the ledger for 5 fixture runs; no per-person human-time field exists in any contract."
Rules that bind: PRD 14.1, 14.2, 14.4, FR-MTR-01/05/10, PE-22, PE-26, PE-27, HR-1, PL-01, EFF-01, NFR-24. Open questions:
`BQ-PA20-1` to `-5`. **No contract change and no new event type**: the time-saved object is `meter.schema.json`
`$defs/time_saved` unchanged. API half only: no screen (S-26 and the HUD read this later).

Files: `test_FR_PA_20_effort_route.py` (route), `test_FR_PA_20_effort_properties.py` (Hypothesis), `test_FR_PA_20_no_human_time.py`
(contract guards, green today), `_fr_pa_20_lib.py` (fixtures). All names carry `FR_PA_20`. The route tests fail today because
`GET /v1/effort` does not exist (`Rig.require_route`) and `tilo_api.deps.get_time_baselines` does not exist.

## 1. Interface

`GET /v1/effort` (new, `tilo_api`; behind the SEC-15 gate; `NoStore` like every `/v1/` answer). No query, no body. Person =
`Principal.user_id` in `deps.ORG_ID`; the world role on the session changes nothing (PE-26).

```json
{
  "credit_usd": 0.005,
  "totals":   {"tasks": 5, "completed_tasks": 3, "credits": 402.0, "usd": 2.01, "time_saved": {...}},
  "meetings": [{"meeting_id": "mt_e1", "world_id": "w_e1", "tasks": 1, "credits": 80.0, "usd": 0.4, "time_saved": {...}}],
  "tasks":    [{"world_id": "w_e1", "run_id": "r_e1", "meeting_id": "mt_e1", "completed": true,
                "credits": 80.0, "usd": 0.4, "time_saved": {...}}]
}
```

`time_saved` is exactly `{minutes, low, high, steering_measured, method_url}` (meter.schema.json `$defs/time_saved`). Key sets
are closed at every level (a test pins them); no title, name, address, user id, profile or model id appears. Rows: `tasks` by
`run_id`, `meetings` by `meeting_id`; the same data in any order gives the same bytes; no clock.

Reads (all behind `Depends`, so tests override them): `deps.get_people_stores` (the person and her meetings),
`deps.get_store` (worlds, events), `deps.get_ledger` (FR-MTR-10's seam, unchanged) and **new** `deps.get_time_baselines()` ->
`{"method_url": "https://...", "units": {unit_type: {"p25": x, "median": y, "p75": z}}}` (minutes per unit; `0 <= p25 <= median <=
p75`; `method_url` as the meter's: https only). Unwired: 503 `not_configured`.

## 2. Numbers

- **Credits** = the sum of the ledger's `commit` entries at their recorded credits (never re-priced; reservations, releases,
  grants and usage are not spend) for the runs of the worlds the person owns (`WorldRecord.run_id` plus run ids on that world's
  events, as FR-MTR-10). `usd` = credits x `credit_usd`. Equal to `/costs` for the same runs. A run with no spend is a task with 0.
- **Time saved** (PRD 14.2): over the world's `building.completed` events, each event id once: `minutes` = sum(`unit_count` x
  median), `low` = sum(x p25), `high` = sum(x p75). A unit type without a baseline counts zero; `unit_count` 0 adds nothing; a
  world with nothing finished is `0, 0, 0` (not null). `steering_measured` is false and nothing is subtracted (BQ-PA20-3).
- **Task** = a run; its `meeting_id` is the person's non-deleted meeting whose `world_id` is its world, else null. **Meeting** row =
  the person's non-deleted meeting; `world_id`, `tasks`, `credits`, `usd`, `time_saved` of the world it names when that world is
  hers, else `world_id` null and zeros (a meeting pointing at someone else's world is indistinguishable from one with no world).
  A deleted meeting is not listed, its world's spend stays a task with `meeting_id` null.
- **Totals** = the sum of the task rows (`tasks`, `completed_tasks` = runs with `world.completed`, `credits`, `usd`, `time_saved`);
  meeting rows are a view and are never added again.

## 3. Refusals

| Case | Answer |
| --- | --- |
| signed out | 401 |
| deployed visitor / undeclared | 403 `under_construction` / `declaration_required` (SEC-15), before any seam |
| no person record in `ORG_ID` (a stranger, or a person of another org) | 404 `{"detail": "not_found"}`, one body |
| a person who owns no world | 200, empty lists, zero totals (with `method_url`) |
| `get_people_stores`, `get_ledger` or `get_time_baselines` unwired, or a malformed baseline sheet | 503 `{"detail": "not_configured"}` |
| a wired source that fails (ledger iteration or seam raises, baselines raise, people store raises) | 503 `{"detail": "unavailable"}` |
| any write method | 405 |

Every one is `Cache-Control: no-store`, carries no figure and no trace, and never a partial body (HR-1).

## 4. Cases (test -> criterion)

| Test | Pins |
| --- | --- |
| `..._the_owner_reads_one_allowlisted_body_with_rows_in_a_fixed_order` | the shape, closed key sets, row order, the deleted meeting absent |
| `..._each_of_the_five_fixture_runs_credits_equal_the_ledger` (x5) | FR-PA-20 acceptance: each run's credits `==` the ledger's commits |
| `..._the_totals_equal_the_ledger_of_the_owners_runs_and_no_one_elses` | totals `==` ledger (402), tasks 5, completed 3, other owner's 120 absent |
| `..._FR_MTR_01_only_committed_spend_counts_...` | an uncommitted reserve is not spend; two price sheets at their own prices |
| `..._FR_MTR_10_the_credits_are_the_cost_report_of_the_same_runs` | `/v1/effort` credits `==` `/costs` per run and in total |
| `..._FR_MTR_05_a_tasks_time_saved_is_...` (x5) | minutes, low, high per run (hand-worked and by the method written out again) |
| `..._FR_MTR_05_every_estimate_has_its_range_and_links_to_the_method` | schema-valid `time_saved`, `low <= minutes <= high`, https method link, on every row |
| `..._FR_MTR_05_steering_is_reported_as_not_measured_...` | `steering_measured` false everywhere, nothing subtracted |
| `..._FR_MTR_05_the_minutes_come_from_the_baselines_seam_...` | a changed baseline changes the numbers; the link is the seam's |
| `..._a_unit_type_without_a_baseline_a_zero_count_and_a_redelivery_add_nothing` | no guess; zero count; one event id once; empty baselines all zero |
| `..._a_run_with_nothing_finished_reports_zero_minutes_...` | zero with a range and a link, not null |
| `..._a_meetings_row_is_its_outpost_worlds_numbers` / `..._without_a_world_...` | per-meeting numbers; zero row |
| `..._a_meeting_pointing_at_someone_elses_world_...` | no foreign number or id; looks like no world |
| `..._a_deleted_meeting_is_gone_but_its_worlds_spend_is_still_a_task` | FR-MTG-10; totals still equal the ledger |
| `..._the_totals_are_the_sum_of_the_task_rows_...` | totals not double counted |
| `..._each_person_reads_only_the_worlds_she_owns`, `..._owns_no_world_gets_zeros` | owner scope; zeros |
| `..._PE_26_a_world_role_on_the_session_changes_nothing` (x3) | roles ignored |
| `..._a_stranger_and_a_person_of_another_org_get_the_same_404_...` | one 404 body, no oracle |
| `..._signed_out_is_401_and_a_deployed_visitor_is_gated_...` | 401; SEC-15 gate |
| `..._unwired_...`, `..._a_failing_ledger_...`, `..._failing_baselines_or_failing_people_stores_...`, `..._a_malformed_baseline_...` | the two fixed 503 bodies, no partial answer |
| `..._PE_22_every_answer_is_no_store_...` | `Cache-Control: no-store` on 200, 404, 503 |
| `..._the_route_is_read_only_and_makes_no_model_call_and_no_live_call` | 405 on writes; no event, no store change, no router, no `LIVE` |
| `..._the_same_data_in_any_order_gives_byte_identical_answers` | determinism |
| `..._the_body_holds_only_numbers_and_the_ids_the_caller_owns` | redaction: titles, names, user ids, org never appear |
| `..._PL_01_no_model_id_and_no_profile_...` | no model id, no profile |
| `..._D_4_no_key_of_the_body_names_a_person_or_human_time` | no per-person or human-time key in the response |
| `test_FR_PA_20_property_...` (Hypothesis, 25 examples) | equality with the ledger, totals = row sums, method oracle, range, meeting = view, closed keys |
| `test_FR_PA_20_no_human_time.py` (4 guards, green today) | no contract names tracked human time; `attention.schema.json` the only person + span schema (BQ-PA20-4) |

## 5. Gaps (no test, decision needed)

- **Baselines are unmeasured.** EV-G2 has no numbers and no `config/` shape exists for them; the seam is tested with a fake sheet.
  A production wiring needs the study or an architect-owned config shape (BQ-PA20-2). Until then the route is 503 `not_configured`.
- **Attention spans** are written by nobody yet in tilo-api (BQ-PA20-3).
- **`attention.schema.json`** is a person-with-span contract; the literal acceptance sentence is read as "no tracked human time"
  (BQ-PA20-4). If the user wants it removed, that is a contract change (major version, ADR), not this ticket.
