# services/api — `tilo-api`

## Purpose
Cloud Run service (PRD 6.2): sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC. The only
service the web client and channels write through; the client reads live state from Firestore under rules.

## Commands
- `uv sync --package tilo-api` — install; `uv run --package tilo-api pytest` — tests; `just check` — root gate
- `just dev-api` — dev mode on 127.0.0.1:8080; `TILO_MODELS_FILE` defaults to `config/models.dev.yaml` (fake Director)

## Contracts
- Reads/writes `packages/contracts-py` types; Firestore (worlds, events, cards, policies, grants); Cloud Tasks.

## Config
- `config/autonomy.yaml`, `config/flags/`, `config/connectors.yaml` (RBAC and routing only).
- Env: `TILO_API_DEV=1` dev mode; `TILO_API_DEV_ORIGINS` comma list (default `http://localhost:5173`).

## Requirement IDs
- Section 6.2 `tilo-api` row; SEC-05 through SEC-12 (auth, RBAC, redaction) as they land.

## Local rules
- Side effects go through the outbox and the deterministic policy engine, T3 only with a person. `/healthz`: ok.
- Dev mode (CL-INT-4, `tilo_api.dev`): one fixed owner `u_dev_owner` (a member of any world it owns), the in-memory
  `Store`, a writer that refuses an event with no `vis`, CORS for `TILO_API_DEV_ORIGINS` only (no `*`, no credentials),
  Host must be loopback:8080. No cloud, no paid call. Start-up and every dev dependency refuse when `K_SERVICE`,
  `CLOUD_RUN_JOB` or live mode is set. Task routes read only `application/json` (415).
- `GET /worlds/{id}/layout` (FR-WLD-05): the run's layout, 404 until built; a non-owner gets an allowlisted view.
- `POST /intake` (FR-INT-01/02, `tilo_api.intake`): multipart `text` + `files` -> 201 task, `world.requested`
  and per-file status, or 422 `{"error": reason}` with nothing stored. Calls `tilo_planning.intake`.
- CP2 flow (CL-INT-1, `tilo_api.tasks`): intake also returns the Director's `brief` and `questions`; then
  `POST /tasks/{id}/answers`, `GET .../approaches`, `POST .../approve`. Principal required; another user's task is
  404. `deps.get_safety` (the `safety` role, 503 without one) screens text, file names, answers and every brief-edit
  string; models only via `deps.get_router`; one budget grant per owner at a time. `tests/API_CL_INT_1.md`, BQ-83.
- Cards (FR-HIL-01/02, `tilo_api.cards`): `GET /worlds/{id}/cards`, `POST .../answer`. Identity is the verified
  `deps.Principal` only; `channel`/`pin_verified` only from a tilo-channels caller. Viewer 403; PRD 10.1 scope. First
  answer wins (400 `already_resolved`, 409 `busy`); one derived `event_id` each. `tests/API_ST3b.md` (Round 2), BQ-69..73.
- Run (CL-INT-2, `tilo_api.runs`): approve starts one run on its own thread if the plan passes `validate_plan`;
  a send waits at a gate card and reaches the outbox only after the owner approves. Every event goes through
  `deps.get_event_writer`; a paused world gets nothing more. `GET .../delivery`: 409 until `world.completed`.
  `tests/API_CL_INT_2.md`, BQ-90.
