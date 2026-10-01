# services/channels — `tilo-channels`

## Purpose
Cloud Run service (PRD 6.2): WhatsApp webhook and sender, email notifications, web push,
channel identity binding. Public ingress for signature-verified webhooks only.

## Commands
- `uv run --package tilo-channels pytest services/channels` — this service's tests.
- `just check` — full gate from the repo root.

## Contracts
- Reads/writes: `packages/contracts-py` event types; writes to `tilo-api` only, never directly
  to Firestore business state.

## Config
- `config/connectors.yaml` (channel routing), feature flags.

## Requirement IDs
- Section 11 (channels and Email Autopilot); SEC-06 (channel identity binding and T3 PIN),
  SEC-08 (signed webhooks and signed email links). FR-CHN-02 and FR-CHN-06 are built.

## Local rules
- Webhooks are signature-verified, idempotent and ordered per user; forged or replayed
  requests are rejected. Email action links are signed, single-use and expire in 24 h.
- Never send a real email or WhatsApp message from dev/CI; fakes or recorded-mode accounts only.
- Never log message bodies, the app secret or full phone numbers (`whatsapp.mask_number`: last 4
  digits). Log exception types, not exception messages.
- `whatsapp`: HMAC over the raw bytes, dedupe via injected `DedupeStore.claim`, serialised per
  sender. Stale = strictly older than `max_age_s` (300 s), claims nothing. Duplicate or replay: 200,
  outcome "duplicate"; forged or missing signature 401; signed non-JSON 400.
- Handler raises: the claim is kept (at-most-once, a partly applied side effect never repeats),
  outcome "failed", still 200 (Meta retries non-2xx), error logged by type only.
- `keywords`: whole-message, case-insensitive; only bound numbers are obeyed; effect through the
  injected control plane, then one confirmation to the sender; a failed effect gets one short
  "Could not apply that" reply.
- Hardening: app secret >= 32 bytes (constructor raises; empty key never verifies); wamids are never
  logged (`message_ref`: sha256 prefix, they encode the number); object, field and `phone_number_id`
  pinned; timestamps more than 60 s ahead are dropped like stale ones (and logged).
