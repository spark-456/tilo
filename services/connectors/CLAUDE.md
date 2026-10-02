# services/connectors — `tilo-connectors`

## Purpose
Cloud Run service (PRD 6.2): OAuth token broker, Gmail and Drive adapters, MCP client, and the
outbox for every side effect. The only service that can decrypt user OAuth tokens.

## Commands
- `uv run pytest services/connectors/tests -q` — public API pinned in `tests/API.md`.
- `just check` — full gate from the repo root.

## Contracts
- Reads `contracts/outbox.schema.json` (+ cross-refs), `data.transfer.schema.json`,
  `contracts/fixtures/outbox/`; calls `tilo_policy.check_entry` for OB-01/OB-05 authorisation.
  Emits `data.transfer` parts via the `emit` callback `Outbox` is constructed with.
- `tokens.py` and `consent.py` (FR-CON-02/03) emit `connection.*` parts `{type, authz, data, user_id}`
  and `alert.raised` via the optional `alert` callback when a revoke fails. `user_id` is the seam:
  the caller picks the world and the actor.

## Config
- Env only, never logged: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_BASE_URL`.
- `config/connectors.yaml` (adapters, scopes), `config/autonomy.yaml` (risk tiers per action).

## Requirement IDs
- Section 12 (connectors, hands and deliverables); SEC-02, SEC-03, SEC-09, SEC-11, SEC-14.

## Local rules
- Side-effect methods are callable only from the outbox (SEC-03); every side-effect event carries
  `authz` (SEC-11). `side_effects.SIDE_EFFECT_METHOD_NAMES` names them; `outbox.py` is the one file
  allowed to call one, and its `Grant` is minted only by `Outbox.dispatch_due()`.
- OAuth only, least privilege, incremental scopes; Tilo never sees, types or stores passwords.
- Exactly-once send, at-least-once delivery: `enqueue` is a no-op on a world_id + idempotency_key
  already stored (OB-03), and the adapter dedupes its own send. `Outbox` may hand the same
  `data.transfer` to `emit` more than once; the event writer (PI-18) keeps one per `outbox_id`.
  Send order holds per `world_id` only.
- Trust boundary: `InMemoryOutboxStore`'s mutators are underscored lock-guarded compare-and-set or
  lease writers, so several instances sharing one store never both win a write.
- Tokens: AES-GCM under a per-record data key wrapped by a `Kms` (`FakeKms` in dev; `CloudKms` is
  unexercised until billing). Only `tokens.py` and `adapters/` call `access_token_for_adapter`; no
  other service imports `tilo_connectors.tokens` (SEC-02). `delete_user` leaves no token in any store
  (CON-D4). Consent state and the revoke-retry store are in memory.
