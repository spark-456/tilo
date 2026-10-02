# services/api — `tilo-api`

## Purpose
Cloud Run service (PRD 6.2): sessions, tasks, cards, approvals, policies, downloads, sharing,
RBAC. The only service the web client and channels write through; the client reads live state
from Firestore directly under security rules.

## Commands
- `uv sync --package tilo-api` — install
- `uv run --package tilo-api uvicorn tilo_api:app --reload --port 8080` — dev server
- `uv run --package tilo-api pytest` — tests
- `just dev` / `just check` — from the repo root

## Contracts
- Reads/writes: `packages/contracts-py` types; Firestore (worlds, events, cards, policies,
  grants); Cloud Tasks to start harness runs.

## Config
- `config/autonomy.yaml`, `config/flags/`, `config/connectors.yaml` (RBAC and routing only).

## Requirement IDs
- Section 6.2 `tilo-api` row; SEC-05 through SEC-12 (auth, RBAC, redaction) as they land.

## Local rules
- Every side effect goes through the outbox and the deterministic policy engine (never here
  directly); T3 actions always require a person to approve.
- `GET /healthz` returns `{"status": "ok"}`.
- `POST /intake` (FR-INT-01/02, `tilo_api.intake`): multipart `text` + `files` -> 201 task, `world.requested`
  and per-file status, or 422 `{"error": reason}` with nothing stored. Calls `tilo_planning.intake`.
- CP2 flow (CL-INT-1, `tilo_api.tasks`): intake also returns the Director's `brief` and `questions`; then
  `POST /tasks/{id}/answers`, `GET .../approaches`, `POST .../approve`. Principal required; another user's task is
  404. `deps.get_safety` (the `safety` role, 503 without one) screens text, file names, answers and every brief-edit
  string; models only via `deps.get_router`; one budget grant per owner at a time. `tests/API_CL_INT_1.md`, BQ-83.
- Cards (FR-HIL-01/02, `tilo_api.cards`): `build_router` serves `GET /worlds/{id}/cards` and `POST .../answer`.
  Identity is the verified `deps.Principal` only; `channel`/`pin_verified` only from a tilo-channels caller. Viewer
  403; PRD 10.1 scope. First answer wins (later: 400 `already_resolved`); one derived `event_id` per resolution (#204).
- Run (CL-INT-2, `tilo_api.runs`): approve starts one run on its own thread if the plan passes `validate_plan`;
  the executor runs it through the run seams in `deps`; a send waits at a gate card in the world's `CardStore` and
  reaches the outbox only after the owner approves. Every event goes through `deps.get_event_writer`; a paused world
  gets nothing more. `GET /worlds/{id}/delivery`: 409 until `world.completed`. `tests/API_CL_INT_2.md`, BQ-90.
