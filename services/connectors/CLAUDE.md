# services/connectors — `tilo-connectors`
## Purpose
Cloud Run service (PRD 6.2): OAuth token broker, Gmail and Drive adapters, MCP client, outbox. Only it decrypts tokens.

## Commands
- `uv run pytest services/connectors/tests -q` — API pinned in `tests/API*.md`; `just check` is the full gate. Image: `Dockerfile` runs `tilo_connectors.app:app` (`/health` for Cloud Run smoke checks, `/healthz` for in-container probes; P0-07a, P0-07h).
- Live Gmail smoke (FR-CON-04; user only): set `LIVE=1` + `GOOGLE_OAUTH_*`, run
  `uv run python services/connectors/scripts/live_gmail_smoke.py [--draft ADDRESS] [--timeout S]`. Only `live.py` reaches Google.

## Contracts
- Reads `contracts/outbox.schema.json` (+ cross-refs), `data.transfer.schema.json`, `contracts/fixtures/outbox/`;
  calls `tilo_policy.check_entry` (OB-01/OB-05). Emits `data.transfer` via the `emit` callback `Outbox` gets.
- `tokens.py`, `consent.py` and `adapters/` emit `connection.*` parts `{type, authz, data, user_id}` (`user_id` is the
  seam: the caller picks the world and actor); a failed revoke raises `alert.raised` via the optional `alert` callback.
  The broker holds no lock while a hook, `emit` or `alert` runs: collect under the lock, call out after (#149).
## Config
- Env only, never logged: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_BASE_URL`.
- `config/connectors.yaml` (gmail, google_drive: scopes, actions), `config/autonomy.yaml` (risk tiers per action),
  `config/mcp.yaml` (FR-CON-12 MCP allowlist, code-validated; side effects T3 only, at most once; empty = none).

## Requirement IDs
- Section 12 (connectors, hands and deliverables; FR-CON-04/05 Gmail, Drive; FR-CON-11 `save_as_google_file` (`tests/API_FR_CON_11.md`); FR-CON-10 manifest, MF-01..06; FR-CHN-08 `watch`/`stop_watch`/`list_history`/`recent_inbox`: read scope, no outbox); FR-CON-12 `mcp.py`; SEC-02, SEC-03, SEC-09, SEC-11, SEC-14. Gmail messages carry a `headers` map: 4 names, lower-case, first of a repeat wins, plus `has_text_part`/`has_other_parts` (BQ-278 n).

## Local rules
- Side-effect methods are callable only from the outbox (SEC-03); every side-effect event carries
  `authz` (SEC-11). `side_effects.SIDE_EFFECT_METHOD_NAMES` names them; `outbox.py` is the one file
  allowed to call one, and its `Grant` is minted only by `Outbox.dispatch_due()`.
- Adapters: every Google call goes through an injected `Transport` (fakes or `recording.ReplayTransport` in dev and
  CI), no logging. A side effect never waits (the lease); `SideEffectRefused` fails the entry, others follow `RetryPolicy`.
- OAuth only, least privilege, incremental scopes; Tilo never sees, types or stores passwords.
- Exactly-once send, at-least-once delivery: `enqueue` is a no-op on a world_id + idempotency_key
  already stored (OB-03), and the adapter dedupes its own send. `Outbox` may hand the same
  `data.transfer` to `emit` more than once; the event writer (PI-18) keeps one per `outbox_id`.
  Send order holds per `world_id` only; `Outbox(world_id=w)` sends and emits only w's; `abandon` fails an unsent entry.
  `get`/`get_by_idempotency_key` are pure reads (copies); `revoke` cancels a scheduled entry or bars its key, never prunes.
- Trust boundary: `InMemoryOutboxStore` mutators are underscored lock-guarded CAS/lease writers: no two instances both win.
- Tokens: AES-GCM under a per-record data key wrapped by a `Kms` (`FakeKms` in dev; `CloudKms` is
  unexercised until billing). Only `tokens.py` and `adapters/` call `access_token_for_adapter`; no
  other service imports `tilo_connectors.tokens` (SEC-02). `delete_user` leaves no token in any store
  (CON-D4). Google keeps one grant per client: never revoke while another connector is connected (CON-D10). Consent state and the revoke-retry store are in memory.
