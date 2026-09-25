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
- FR-HIL-07 (kill switches), FR-HIL-09 and SEC-07 (roles and redaction), PI-13
  (`docs/security/p4-policy-invariants.md`): ticket ST-3a.

## Local rules
- Every side effect goes through the outbox and the deterministic policy engine (never here
  directly); T3 actions always require a person to approve.
- `GET /healthz` returns `{"status": "ok"}`.
- `tilo_api.deps` (`Principal`, `Store`, `WorldRecord`, `DistrictRecord`,
  `get_current_principal`, `get_store`): the auth and storage seams every route depends on via
  FastAPI overrides. Real sign-in and Firestore are later tickets — both raise
  `NotImplementedError` in production so a route can never run silently unauthenticated or
  against no store. `tilo_api.events` builds this service's own `event.schema.json` parts
  (`policy_changed_event`, `world_paused_event`); every field not supplied by the caller is
  filled with the schema's own default (`null`, `"all"`, `"info"`), never invented.
- Five routes (ST-3a, exact shape in `services/api/tests/API_ST3a.md`):
  `POST /worlds/{world_id}/autopilot/stop`, `POST /worlds/{world_id}/pause`,
  `POST /policies/{policy_id}/revoke`, `GET /worlds/{world_id}/events`,
  `GET /worlds/{world_id}`. Only the policy's owner may stop, pause or revoke (403 otherwise,
  store unchanged); Stop all and Pause all are idempotent per call (a policy already at `"L1"`
  is skipped, no duplicate history entry or `policy.changed` event); Revoke is not (always
  appends, since it is a distinct explicit act). Redaction on the two `GET` routes is
  server-side and fail closed: an event whose `vis` the principal cannot see, or a hidden
  district, is dropped entirely from the response — never returned with blanked fields — so no
  hidden id, name, summary or count leaks (PRD 10.1, SEC-07).
- `Store.policy_worlds` (`policy_id -> world_id`) is this service's own bookkeeping to route a
  policy's `policy.changed` events to the right world's stream; `policy.schema.json` itself
  carries no `world_id` (PRD 15.3 keeps policies at the org level).
