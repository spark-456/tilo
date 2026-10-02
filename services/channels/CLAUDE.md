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
  SEC-08 (signed webhooks and signed email links). FR-CHN-02, -03, -06, -07 are built.

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
- `links` (FR-CHN-07; BQ-76 to BQ-82): HMAC-SHA256 (`compare_digest`, prefix `tilo-link-v1|`), every
  segment alphabet-checked before the MAC, claims parsed after; key ring live; nonce consumed last. Answer
  only for plain needs_you cards listing email (allowlist, fail closed); gate, consent, meeting open
  only signed in. Naive clock refused. HTTP layer (BQ-82): `answer` needs a POST confirm (a scanner GET
  never answers); token in a URL fragment, not the path; public non-consuming verify; no consume on
  requires_sign_in; first answer is a compare-and-set on the card; whether `open` needs a POST too.
- `binding` (FR-CHN-03; BQ-89): numbers stored only via the injected cipher, looked up by HMAC (key >= 32
  bytes); codes stored only as an HMAC, 6 digits, 10 min, 5 attempts claimed as atomic `try:<pid>:<i>`
  slots; a binding counts only while `num:` and `user:` records agree and `now < verified_at + 30 d`.
- `inbound`: unbound sender -> one fixed opt-in text with the web URL, nothing else runs; bound ->
  keywords, then cards, else `unhandled` (FR-CHN-04).
