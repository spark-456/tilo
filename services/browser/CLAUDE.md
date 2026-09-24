# services/browser — `tilo-browser`

## Purpose
Cloud Run service with a proxy sidecar (PRD 6.2): one isolated headless browser per session,
allowlisted egress, masked secure fields, nothing persisted between runs.

## Commands
- Package and dev/test commands land with the browser-worker code (ticket P6).
- `just check` — full gate from the repo root.

## Contracts
- Reads/writes: `packages/contracts-py` task/result types via `tilo-harness`; masked
  screenshots to Cloud Storage.

## Config
- `config/connectors.yaml` (egress allowlist per adapter).

## Requirement IDs
- Section 6.2 `tilo-browser` row; SEC-09 (egress allowlist for browsers).

## Local rules
- One isolated browser per session; egress only through the allowlist proxy.
- Secure fields (passwords, payment) are masked and never persisted or logged.
- `tilo-browser` cannot read Firestore or Cloud Storage business data directly.
- Nothing from a run is kept once the run ends.
