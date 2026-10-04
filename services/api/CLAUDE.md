# services/api — `tilo-api`

## Purpose
Cloud Run service (PRD 6.2): sessions, tasks, cards, approvals, policies, downloads, sharing, RBAC. The only
service the web client and channels write through; the client reads live state from Firestore under rules.

## Commands
- `uv sync --package tilo-api` — install; `uv run --package tilo-api pytest` — tests; `just check` — root gate
- `just dev-api` — dev mode on 127.0.0.1:8080; `TILO_MODELS_FILE` defaults to `config/models.dev.yaml` (fake Director)

## Requirement IDs
- PRD 6.2 row; SEC-05..12 (auth, RBAC, redaction) as they land; FR-INT-11/12, FR-HIL-10 (API half).

## Contracts and config
- Reads/writes `packages/contracts-py` types; Firestore (worlds, events, cards, policies, grants); Cloud Tasks. Config:
  `autonomy.yaml`, `flags/`, `connectors.yaml` (RBAC and routing only), `teams.yaml`, `scenarios/`, `out_of_policy.yaml`.
- Env: `TILO_API_DEV=1` dev mode; `TILO_API_DEV_ORIGINS` (default `http://localhost:5173`); `TILO_DEV_UNIT_DELAY_S` (default 1.5, 0..10).

## Local rules
- Side effects go through the outbox and the deterministic policy engine, T3 only with a person. `/healthz`: ok.
- Dev mode (CL-INT-4, `tilo_api.dev`): fixed owner `u_dev_owner`, the in-memory `Store` (a restart loses every task and
  world), a writer that refuses an event with no `vis`, CORS for `TILO_API_DEV_ORIGINS` only, Host loopback:8080. No
  cloud, no paid call; task routes read only `application/json` (415); refuses when `K_SERVICE`, `CLOUD_RUN_JOB` or live
  is set. `dev_run` (CL-INT-5c/5d): a paced unit runner (one synthetic artifact, `config/prices.dev.yaml`), a fake recipient.
- `GET /worlds/{id}/layout` (FR-WLD-05): the run's layout, 404 until built; owner gets `tilo_world` geometry (CL-INT-6, null if invalid); others an allowlisted view, geometry null.
- `POST /intake` (FR-INT-01/02/11/12): multipart `text`, `files`, optional `scenario` -> 201 task, per-file status; or 422
  `{"error": reason}`, nothing stored (a refusal adds `alternative`, `category`: config text; a bad scenario id is 422).
  Approve creates the scenario's policies as the owner's own, one `policy.changed` each, once.
- Team Lead console (FR-HIL-10, `tilo_api.console`): `GET /worlds/{id}/console`, `POST .../console/cards/{id}/answer`;
  role `team_lead` + a `config/teams.yaml` record; only questions routed to its domain (`CardStore.submit(domain=)`).
- CP2 flow (CL-INT-1, `tilo_api.tasks`): intake also returns the `brief` and `questions`; then `POST /tasks/{id}/answers`,
  `GET .../approaches`, `POST .../approve`. Principal required; another user's task is 404. `deps.get_safety` (the
  `safety` role, 503 without one) screens every typed string; models only via `deps.get_router`; one budget grant per
  owner at a time. `tests/API_CL_INT_1.md`, BQ-83.
- Cards (FR-HIL-01/02, `tilo_api.cards`): `GET /worlds/{id}/cards`, `POST .../answer`. Identity is the verified
  `deps.Principal` only; `channel`/`pin_verified` only from a tilo-channels caller. Viewer 403; PRD 10.1 scope. First
  answer wins (400 `already_resolved`, 409 `busy`); one derived `event_id` each. `tests/API_ST3b.md` (Round 2), BQ-69..73.
- Run (CL-INT-2, `tilo_api.runs`): approve starts a run if the Director's plan (`deps.get_plan_compiler`, FR-INT-09)
  passes `validate_plan`; a send waits at a gate card, then the outbox after the owner approves. Events go through
  `deps.get_event_writer`; paused gets none. `GET .../delivery`: 409 until `world.completed`. `tests/API_CL_INT_2.md`.
