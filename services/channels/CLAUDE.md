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
- Never log message bodies, the app secret, or phone numbers in full (mask to the last 4 digits,
  `whatsapp.mask_number`). Log exception types, not exception messages.

## WhatsApp webhook (FR-CHN-02) and keywords (FR-CHN-06)
- `tilo_channels.whatsapp`: signature over the raw bytes (`hmac.compare_digest`), then dedupe through
  the injected `DedupeStore.claim` (atomic set-if-absent), processing serialised per sender. Stale means
  strictly older than `max_age_s` (default 300 s) and claims nothing. Duplicates and replays answer 200
  with outcome "duplicate"; forged or missing signatures 401; signed non-JSON 400.
- Handler errors: the dedupe claim is kept (at-most-once, so a partly applied side effect is never
  repeated), the outcome is "failed", the webhook still answers 200 (Meta retries non-2xx) and the
  error is logged with type only. Anything that must survive a handler failure belongs to the handler.
- `tilo_channels.keywords`: whole-message, case-insensitive keywords; only bound numbers are obeyed;
  the effect goes through the injected control plane, then one confirmation to the sender.
- Package commands: `uv run --package tilo-channels pytest services/channels`.
