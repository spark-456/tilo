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
- CP2 flow (CL-INT-1, `tilo_api.tasks`): `POST /intake` also returns the Director's `brief` and `questions`;
  `POST /tasks/{id}/answers`, `GET /tasks/{id}/approaches`, `POST /tasks/{id}/approve`. Every route needs the
  principal; another user's task is a 404. Safety (`deps.get_safety`) is built from the `safety` role at call
  time (503 without one) and screens the text, file names, typed answers and every brief-edit string; model
  calls go only through `deps.get_router`; the grant is `tilo_planning.budget` with the person's cap, one
  grant per owner at a time (`Store.grant_lock`). Shapes: `services/api/tests/API_CL_INT_1.md`; defaults: BQ-75.
- Cards (FR-HIL-01/02, `tilo_api.cards`): `build_router(CardStore)` serves `GET /worlds/{id}/cards` and
  `POST .../cards/{card_id}/answer`. Identity is the verified `deps.Principal` only; `channel` and
  `pin_verified` count only from an authenticated tilo-channels caller (`get_channels_caller`). Viewer 403;
  scope per PRD 10.1. Shapes and defaults: `services/api/tests/API_ST3b.md` (Round 2), BQ-69 to BQ-73.
