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
- Section 6.2; SEC-05..12; FR-HIL-07/09, SEC-07, PI-13, PI-18 (`docs/security/p4-policy-invariants.md`): ST-3a.

## Local rules
- Every side effect goes through the outbox and the deterministic policy engine (never here
  directly); T3 actions always require a person to approve.
- `GET /healthz` returns `{"status": "ok"}`.
- One writer (PI-18): routes build unstamped event *parts*, never touching `id`/`seq`/`ts`/
  `run_id`. A writer failure queues the part in `Store.pending_events`; every mutating call
  flushes/counts `pending` for every world its owned policies touch, not only its own. Per-world
  locks (never one global lock) plus concurrent writer calls (a thread pool) keep world A's
  Stop-all from ever waiting on world B's writer, holding the 5s budget against a slow writer.
- `Principal.world_id` binds a principal to one world; every world route/revoke 404s the same
  for unknown vs. not-yours. Five ST-3a routes (`services/api/tests/API_ST3a.md`): stop/pause
  (owner-only, 200/202 on `pending`), revoke, two `GET` reads. Stop-all/pause validate first, never 500:
  L0 untouched; L1 skipped only when history agrees (no silent repair); else lowered, `vis` the
  intersection of `scope.districts` with the policy's *target* world. Pause dedupes on
  `WorldRecord.paused`, not whether a policy changed. `GET` routes **allowlist** each kept event:
  dense `seq`/`id` (`v{seq}`), `vis`/`district`/`target`/`actor` filtered to the caller's
  districts, `data` redacted recursively. Malformed events/districts drop for all, owner included.
