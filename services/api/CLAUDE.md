# services/api — `tilo-api`

## Purpose
Cloud Run service (PRD 6.2): sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC. The only
service the web client and channels write through; the client reads live state from Firestore under rules.

## Commands
- `uv sync --package tilo-api` — install; `uv run --package tilo-api pytest` — tests; `just check` — root gate
- `just dev-api` — dev mode on 127.0.0.1:8080; `TILO_MODELS_FILE` defaults to `config/models.dev.yaml` (fake Director)

## Contracts and config
- Reads/writes `packages/contracts-py` types; Firestore (worlds, events, cards, policies, grants); Cloud Tasks.
- `config/autonomy.yaml`, `config/flags/`, `config/connectors.yaml` (RBAC and routing only).
- Env: `TILO_API_DEV=1` dev mode; `TILO_API_DEV_ORIGINS` comma list (default `http://localhost:5173`);
  `TILO_DEV_UNIT_DELAY_S` seconds per dev unit (default 1.5, clamped 0..10; the dev suite sets 0).

## Requirement IDs
- Section 6.2 `tilo-api` row; SEC-05 through SEC-12 (auth, RBAC, redaction) as they land.

## Local rules
- Side effects go through the outbox and the deterministic policy engine, T3 only with a person. `/healthz`: ok.
- Dev mode (CL-INT-4, `tilo_api.dev`): fixed owner `u_dev_owner`, the in-memory `Store` (an API restart loses every
  task and world), a writer that refuses an event with no `vis`, CORS for `TILO_API_DEV_ORIGINS` only, Host loopback:8080.
  No cloud, no paid call; task routes read only `application/json` (415). Start-up and every dev dependency refuse when `K_SERVICE`, `CLOUD_RUN_JOB` or live is set.
  `dev_run` (CL-INT-5c/5d) wires the run seams only here: a unit runner (paced, one synthetic artifact, cost metered
  by `tilo_metering` from `config/prices.dev.yaml`, a dev-only price, on that artifact's event), one fake recipient, mock adapters.
- `GET /worlds/{id}/layout` (FR-WLD-05): the run's layout, 404 until built; owner gets `tilo_world` geometry (CL-INT-6, null if invalid); others an allowlisted view, geometry null.
- `POST /intake` (FR-INT-01/02, `tilo_api.intake`): multipart `text` + `files` -> 201 task, `world.requested`
  and per-file status, or 422 `{"error": reason}` with nothing stored. Calls `tilo_planning.intake`.
- CP2 flow (CL-INT-1, `tilo_api.tasks`): intake also returns the Director's `brief` and `questions`; then
  `POST /tasks/{id}/answers`, `GET .../approaches`, `POST .../approve`. Principal required; another user's task is
  404. `deps.get_safety` (the `safety` role, 503 without one) screens text, file names, answers and every brief-edit
  string; models only via `deps.get_router`; one budget grant per owner at a time. `tests/API_CL_INT_1.md`, BQ-83.
- Cards (FR-HIL-01/02, `tilo_api.cards`): `GET /worlds/{id}/cards`, `POST .../answer`. Identity is the verified
  `deps.Principal` only; `channel`/`pin_verified` only from a tilo-channels caller. Viewer 403; PRD 10.1 scope. First
  answer wins (400 `already_resolved`, 409 `busy`); one derived `event_id` each. `tests/API_ST3b.md` (Round 2), BQ-69..73.
- Run (CL-INT-2, `tilo_api.runs`): approve starts a run if the Director's plan (`deps.get_plan_compiler`, FR-INT-09)
  passes `validate_plan`; a unit may ask first (`MustAsk`, `deps.get_must_ask_providers`; `QuestionWait` holds it, no
  `world.completed` while one waits, BQ-235..237; its card is never merged, #338); a send waits at a gate card, then the outbox after the owner approves.
  Events via `deps.get_event_writer`; paused gets none. A `deliver` unit delivers in_app, ungated. `replay_only` (NFR-24, process-wide flag, BQ-238) closes intake, answers, approaches, approve: 503 `replay_only: true`. `GET .../delivery`: 409 until `world.completed`. `tests/API_CL_INT_2.md`.
