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
- FR-HIL-07/09, SEC-07, PI-13 (`docs/security/p4-policy-invariants.md`): ticket ST-3a.

## Local rules
- Every side effect goes through the outbox and the deterministic policy engine (never here
  directly); T3 actions always require a person to approve.
- `GET /healthz` returns `{"status": "ok"}`.
- `tilo_api.deps`: `Principal`/`Store` test doubles, injected via FastAPI overrides;
  `get_current_principal`/`get_store` raise `NotImplementedError` until real sign-in and
  Firestore land. `tilo_api.events` builds `policy.changed`/`world.paused` event parts.
- Five ST-3a routes (exact shape in `services/api/tests/API_ST3a.md`): stop/pause/revoke
  (owner-only, 403 otherwise, store unchanged) and two `GET` reads. Stop-all/Pause-all only
  lower autonomy and are idempotent per call: an L1 policy is skipped, an L0 policy is left
  alone (no history entry, no event); Revoke always appends. Redaction on the `GET` routes is
  server-side and fail closed: a hidden event or district is dropped entirely, never returned
  with blanked fields (PRD 10.1, SEC-07).
- `Store.policy_worlds` (`policy_id -> world_id`) routes a policy's `policy.changed` events to
  the right world's stream; `policy.schema.json` itself carries no `world_id` (PRD 15.3).
