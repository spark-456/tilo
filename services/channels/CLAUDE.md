# services/channels — `tilo-channels`

## Purpose
Cloud Run service (PRD 6.2): WhatsApp webhook and sender, email notifications, web push,
channel identity binding. Public ingress for signature-verified webhooks only.

## Commands
- `uv run --package tilo-channels pytest services/channels`; `just check` from the repo root.

## Contracts
- `packages/contracts-py` event types; writes to `tilo-api` only, never to Firestore business state.

## Config
- `config/connectors.yaml` (channel routing), feature flags.

## Requirement IDs
- Section 11 (channels and Email Autopilot); SEC-06 (channel identity binding and T3 PIN),
  SEC-08 (signed webhooks and signed email links). FR-CHN-02, -06, -07 are built.

## Local rules
- Webhooks are signature-verified, idempotent, ordered per user; forged or replayed requests are
  rejected. Email action links are signed, single-use, 24 h.
- Never send a real email or WhatsApp message from dev/CI; fakes or recorded-mode accounts only.
- Never log message bodies, secrets, tokens, nonces or full phone numbers (`whatsapp.mask_number`:
  last 4 digits). Log exception types, not exception messages.
- `whatsapp`: HMAC over the raw bytes, dedupe via injected `DedupeStore.claim`, serialised per
  sender. Stale = strictly older than `max_age_s` (300 s), claims nothing. Duplicate or replay: 200,
  outcome "duplicate"; forged or missing signature 401; signed non-JSON 400. Handler raises: claim
  kept (at-most-once), outcome "failed", still 200 (Meta retries non-2xx), error logged by type only.
- `keywords`: whole-message, case-insensitive; only bound numbers obeyed; effect through the injected
  control plane, then one confirmation; a failed effect gets one short "Could not apply that" reply.
- Hardening: app secret >= 32 bytes (constructor raises; empty key never verifies); wamids never
  logged (`message_ref`: sha256 prefix, they encode the number); object, field and `phone_number_id`
  pinned; timestamps over 60 s ahead are dropped like stale ones (and logged).
- `links` (FR-CHN-07; BQ-75 to BQ-81): HMAC-SHA256 via `hmac.compare_digest`, signature checked before
  claims; key ring read live; nonce consumed last (atomic), so a refusal never burns a link. 24 h expiry;
  `answer` only for needs_you cards listing email, never gate or consent; opening a gate, consent or
  meeting card without sign-in yields `requires_sign_in`; another signed-in viewer is refused; unknown or
  retired key id is `unknown_key`; an answered card is `card_answered`. HTTP layer: `answer` must need a
  POST confirm; a GET (scanner prefetch) only shows the card and never calls `redeem` for `answer`.
