# FR-AGT-14h interface (Cloud Tasks quota and server errors become a signal)

Follow-up to FR-AGT-14g (issue #502; BQ-AGT14-7 "Open": NFR-23 asks for alerts on quota errors, and a sustained 429/5xx
stream still disables every schedule quietly). Builds on `API_FR_AGT_14g.md`; no contract change, no new route, no
Terraform change. Decisions: BQ-AGT14-8. Tests: `test_FR_AGT_14h_quota_signal.py` (a `requests.Session`-shaped Cloud
Tasks session for the real `CloudTasksRestClient`; no network) and `tests/repo/test_FR_AGT_14h_schedules_doc.py`.

## 1. The status is a structured field (NFR-23, NFR-26)

A per-schedule enqueue failure that carries an HTTP status (400, 409 ABORTED, 429, 500, 502, 503, 504) is logged once at
WARNING on `tilo_api.schedules` or `tilo_harness.schedule` with these `extra` fields:

| Field | Value |
|---|---|
| `event` | `"schedule_enqueue_failed"` |
| `status` | the HTTP status, an `int` |
| `code` | the code recorded against the schedule (its `last_error`, today `start_failed`) |

Ids only: no task name, queue, URL, account email, token, exception text or traceback (`exc_info` unset); any `%`
argument is an int or an identifier; every other `extra` value is an int or matches `[A-Za-z0-9_]{1,64}`. The field
names are constants at the top of the test file: the cloud lane's quota alert filters on them, and they may still be
renamed there (one place).

## 2. The first two calls failing alike are the service's

When the FIRST TWO enqueue calls of a Scheduler tick both fail with the same HTTP status, and that status is 429 or a 5xx
(the exact status decides: 502 then 503 is mixed):

- no further enqueue call is made that tick;
- NEITHER of the two slots is counted (no failure, no backoff, no `last_error`, `next_due` unmoved, claim released), and
  every later due slot stays due; a tick one minute later hands them all over once;
- the tick answers `503 {"detail": "tasks_quota"}` (429) or `503 {"detail": "tasks_server"}` (5xx): a fixed body;
- one ERROR line per stopped tick on a `tilo_api.*` logger, naming the code, with `status` (int) and `code` as the same
  structured fields as item 1; no schedule or owner id, no exception text.

## 3. Everything else is unchanged (counted per schedule, 200)

A lone due slot (one call cannot tell), a success or ALREADY_EXISTS before the failures, two different statuses, a 400 or
409 ABORTED (never service-wide), an unclassified exception on either of the first two calls: every failure is counted
against its own schedule as in 14g and the tick goes on. 14e, 14f and 14g behaviour (401/403/404, credential and
transport outages, replay-only, nothing due, Tasks-mode delivery) is unchanged.

## 4. Docs

The FR-AGT-14 notes (14b, 14d, 14e, 14f, 14g) move from `services/api/CLAUDE.md` to `docs/schedules.md` (written
verbatim in the tests commit); the builder adds a 14h line there (naming `tasks_quota`, `tasks_server`, BQ-AGT14-8) and
replaces the notes in `services/api/CLAUDE.md` with a link, keeping it at or under 40 lines.

## Known test conflicts (reported, not edited)

Item 2 changes what two existing tests pin for three due slots all answering the same 429/5xx (they expect all three
counted and 200):

- `test_FR_AGT_14f_tasks_unavailable.py::test_FR_AGT_14f_a_per_schedule_tasks_error_is_counted_and_does_not_stop_the_tick`
  for `status` 429, 500, 503 (400 still holds);
- `test_FR_AGT_14g_credential_outage.py::test_FR_AGT_14g_quota_and_server_errors_still_count_per_schedule_and_the_tick_goes_on`
  for every `status` (429, 500, 502, 503, 504).

Under 14h those ticks make two calls, count nothing and answer 503 `tasks_quota` / `tasks_server`. The builder PR changes
them deliberately (for example to a single due slot, or to different statuses) and lists the change.
