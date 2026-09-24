# services/connectors — `tilo-connectors`

## Purpose
Cloud Run service (PRD 6.2): OAuth token broker, Gmail and Drive adapters, MCP client, and the
outbox for every side effect. The only service that can decrypt user OAuth tokens.

## Commands
- Package and dev/test commands land with the connectors code (ticket P6).
- `just check` — full gate from the repo root.

## Contracts
- Reads/writes: `packages/contracts-py` outbox/event types; Secret Manager and Cloud KMS for
  token envelope encryption; Google Workspace APIs.

## Config
- `config/connectors.yaml` (adapters, scopes), `config/autonomy.yaml` (risk tiers per action).

## Requirement IDs
- Section 12 (connectors, hands and deliverables); SEC-02, SEC-03, SEC-09, SEC-11, SEC-14.

## Local rules
- Connector side-effect methods are callable only from the outbox (SEC-03); every side-effect
  event carries `authz` (SEC-11).
- OAuth only, least privilege, incremental scopes; Tilo never sees, types or stores passwords.
- Every side effect goes through the outbox exactly once (idempotency keys, no duplicate retries).
