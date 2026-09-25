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
- One writer (PI-18): routes build unstamped event *parts* (`tilo_api.events`), never touching
  `id`/`seq`/`ts`/`run_id`. A writer failure never blocks the level change: the part goes to
  `Store.pending_events`, flushed oldest-first on the next stop/pause for that world; stop/pause
  serialize under one lock so concurrent calls never double-write.
- `Principal.world_id` binds a principal to one world; every world route and revoke 404s
  identically for unknown vs. not-yours.
- Five ST-3a routes (`services/api/tests/API_ST3a.md`): stop/pause (owner-only, 200/202 on
  `pending`), revoke, two `GET` reads. Stop-all/pause validate every policy first (never 500):
  L0 untouched; L1 skipped only when history agrees (no silent repair); else lowered, `vis` the
  intersection of `scope.districts` with the world (EV-13). `GET` routes rebuild each kept event
  by **allowlisting**, never copying forward: a scoped view has its own dense `seq`/`id`
  (`v{seq}`), a hidden `district`/`cause`/ULID data ref is nulled or remapped, `archive_ref` and
  `message_ref` always null. Malformed events/districts drop for all, owner included.
