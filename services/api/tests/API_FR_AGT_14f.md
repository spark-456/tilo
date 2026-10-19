# FR-AGT-14f interface (a service-wide Cloud Tasks refusal is loud and cheap)

Follow-up to FR-AGT-14e (issue #502, the 7 Oct delta-review comment, and item 8 "stop the tick after the first
`count=False` skip"). Builds on `API_FR_AGT_14e.md`; no contract change, no new route, no Terraform change.
Decisions: BQ-AGT14-6. Tests: `test_FR_AGT_14f_tasks_unavailable.py` (fakes: `FakeTasksClient` from `_fr_agt_14_lib.py`
and a recording `requests.Session`-shaped session for the real `CloudTasksRestClient`; no network).

Why: a 401/403/404 from Cloud Tasks (a revoked actAs or enqueuer role, a deleted queue) is the service's, not one
schedule's (`TasksUnavailable` -> `StartSkipped("tasks_unavailable", count=False)`). Before 14f the tick logged it as one
WARNING, answered 200 `{"fired": 0}` and tried every due slot each minute (up to `MAX_FIRES_PER_TICK` = 20 calls that
cannot succeed), so every scheduled run stopped with nothing visible.

## Fan-out (the Scheduler's call of `POST /internal/schedules/tick`)

1. **The first refusal stops the tick.** After the first `tasks_unavailable` in a tick, no further enqueue call is made
   that tick. The refused slot and every later due slot stay due: no failure counted, no backoff, `next_due` unmoved,
   `last_error` unset, claim released (a tick one minute later, inside the 5-minute lease, hands them all over).
   Slots handed over earlier in the same tick stay completed and are not handed over again.
2. **503 with a fixed body.** A tick whose outcome includes `tasks_unavailable` answers
   `503 {"detail": "tasks_unavailable"}` (the same for 401, 403 and 404; no exception or provider text). This holds even
   when a slot was handed over before the refusal (BQ-AGT14-6 a). Cloud Scheduler records each such tick as a failed
   attempt, and NFR-23's error-rate alert sees it.
3. **One ERROR line per tick** on a `tilo_api.*` logger, naming the code `tasks_unavailable` and the HTTP status (when the
   real client saw one), plus counts at most. Never a token, task name, queue path, service-account email, schedule or
   owner id, exception text or traceback (`exc_info` unset; any `%` argument is an int or a fixed `[a-z0-9_]` code).
4. **Nothing else changes.** A per-schedule failure (400, 429, 500, 503, any other exception) is counted against that
   schedule and the tick goes on (200 `{"fired": n}`, no ERROR line for it); ALREADY_EXISTS is a success; replay-only
   answers 200 `{"fired": 0}` and calls nothing; with nothing due no call is made and the answer is 200 `{"fired": 0}`.

The Tasks-mode delivery (`_run_task`) is unchanged.

## Known test conflict

`test_FR_AGT_14e_fanout.py::test_FR_AGT_14e_a_service_wide_tasks_failure_counts_against_no_schedule` asserts
`tick().json() == {"fired": 0}` on a refused tick; under item 2 that tick answers 503 `{"detail": "tasks_unavailable"}`.
Its other assertions (nothing recorded, the same slots fire at once after the fix) still hold. Reported by the
test-writer, not edited; whoever changes that line lists it in the PR as a deliberate change.
