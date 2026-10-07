# Scheduled runs on tilo-api (FR-AGT-14)

Notes for `tilo_api.schedules` and the tick route, moved verbatim from `services/api/CLAUDE.md`. Decisions live in `docs/open-questions.md` (BQ-AGT14-*); each step's interface is in
`services/api/tests/API_FR_AGT_14*.md`. The harness side (`schedule.Ticker`, `schedule_store`) is in
`services/harness/CLAUDE.md`.

- FR-AGT-14b (`tilo_api.schedules`, `tests/API_FR_AGT_14b.md`, ADR-0023): `/schedules` routes snapshot a task the owner approved (404 for others); `POST /internal/schedules/tick` (own OIDC check: `TILO_SCHEDULE_TICK_AUDIENCE`, `TILO_SCHEDULE_TICK_CALLER`, 503 unset) starts runs only on the owner's L3 `grant_budget` policy; store `TILO_SCHEDULES_STORE`=memory (dev default) or firestore + `TILO_FIRESTORE_PROJECT`.
- 14d (`tests/API_FR_AGT_14d.md`, BQ-AGT14-4): the tick builds the store and run seams (factories) only after the token passed; the shared Google verifier caches certs 900 s, 3 s fetch timeout, logs only the error type name.
- 14e (`tests/API_FR_AGT_14e.md`, BQ-AGT14-5): one route, two callers, never crossed: the Scheduler (no body) only hands each due slot to Cloud Tasks (`TILO_RUNS_QUEUE`, the task's OIDC identity `TILO_TASKS_CALLER`) and starts nothing; Cloud Tasks (the task body) runs ONE run in its own request and answers when it is done or parked (`Run.wait_until_parked_or_done`); either env unset: 503.
- 14f (BQ-AGT14-6): the first Tasks 401/403/404 stops the fan-out (that slot and later ones stay due), 503 `tasks_unavailable`, one ERROR line (code, status, counts).
- 14g (BQ-AGT14-7): an enqueue's google-auth `RefreshError` (`tasks_credential`), `TransportError` or requests `Timeout`/`ConnectionError` (`tasks_transport`) stop it the same way.
