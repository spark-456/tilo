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
- FR-HIL-07/09, SEC-07, PI-13, PI-18 (`docs/security/p4-policy-invariants.md`): ticket ST-3a.

## Local rules
- Every side effect goes through the outbox and the deterministic policy engine (never here
  directly); T3 actions always require a person to approve.
- `GET /healthz` returns `{"status": "ok"}`.
- One writer (PI-18): `tilo_api.deps.EventWriter`/`get_event_writer` stand in for the harness;
  routes build unstamped event *parts* (`tilo_api.events`), never touching `id`/`seq`/`ts`/`run_id`.
- `Principal.world_id` binds a principal to one world; every world route, and revoke, 404s
  identically for "unknown" and "not yours" (no oracle).
- Five ST-3a routes (exact shape in `services/api/tests/API_ST3a.md`): stop/pause/revoke
  (owner-only) and two `GET` reads. Stop-all/pause validate every policy's plan before mutating
  (never half-apply, never 500): L0 untouched, L1 idempotent (history repaired if inconsistent,
  no event), else lowered fail-safe. `policy.changed`'s `vis` follows `scope.districts`. A
  scoped `GET` view has its own dense `seq` and nulls a `cause` naming a hidden event; a
  malformed district record is hidden, never raises.
- `Store.policy_worlds` routes `policy.changed`; absent an entry, stop/pause use the request's
  own world, revoke emits no event (PRD 15.3).
