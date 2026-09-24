# services/channels — `tilo-channels`

## Purpose
Cloud Run service (PRD 6.2): WhatsApp webhook and sender, email notifications, web push,
channel identity binding. Public ingress for signature-verified webhooks only.

## Commands
- Package and dev/test commands land with the channels code (ticket P5).
- `just check` — full gate from the repo root.

## Contracts
- Reads/writes: `packages/contracts-py` event types; writes to `tilo-api` only, never directly
  to Firestore business state.

## Config
- `config/connectors.yaml` (channel routing), feature flags.

## Requirement IDs
- Section 11 (channels and Email Autopilot); SEC-06 (channel identity binding and T3 PIN),
  SEC-08 (signed webhooks and signed email links).

## Local rules
- Webhooks are signature-verified, idempotent and ordered per user; forged or replayed
  requests are rejected.
- Email action links are signed, single-use and expire in 24 h.
- Never send a real email or WhatsApp message from dev/CI — fakes or recorded-mode test
  accounts only.
