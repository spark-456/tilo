# services/connectors — `tilo-connectors`

## Purpose
Cloud Run service (PRD 6.2): OAuth token broker, Gmail and Drive adapters, MCP client, and the
outbox for every side effect. The only service that can decrypt user OAuth tokens.

## Commands
- `uv run pytest services/connectors/tests -q` — public API pinned in `tests/API.md` (ticket
  ST-2: `tilo_connectors`, the outbox).
- `just check` — full gate from the repo root.

## Contracts
- Reads `contracts/outbox.schema.json` (+ cross-refs), `data.transfer.schema.json`,
  `contracts/fixtures/outbox/`; calls `tilo_policy.check_entry` for OB-01/OB-05 authorisation.
  Writes: emits `data.transfer` parts (a registered type, no new one) via the `emit` callback
  `Outbox` is constructed with. Token broker / Workspace APIs / KMS land with a later ticket.

## Config
- `config/connectors.yaml` (adapters, scopes), `config/autonomy.yaml` (risk tiers per action).

## Requirement IDs
- Section 12 (connectors, hands and deliverables); SEC-02, SEC-03, SEC-09, SEC-11, SEC-14.

## Local rules
- Connector side-effect methods are callable only from the outbox (SEC-03); every side-effect
  event carries `authz` (SEC-11). `side_effects.SIDE_EFFECT_METHOD_NAMES` names them (currently
  `send_reply`), `scan_for_side_effect_calls` is the static AST check, and `outbox.py` is the one
  file allowed to call one; its `Grant` is minted only by `Outbox.dispatch_due()`.
- OAuth only, least privilege, incremental scopes; Tilo never sees, types or stores passwords.
- Every side effect goes through the outbox exactly once: `Outbox.enqueue` is a no-op on a
  world_id + idempotency_key already stored (OB-03), and a connector adapter (`fakes.FakeGmail`
  today) dedupes its own send by `idempotency_key` too, so a crash between the adapter call and
  `dispatch_due()` recording "sent", followed by a retry, still sends once.
- `InMemoryOutboxStore` is dev/test-only; a Firestore-backed store ships with a later ticket.
