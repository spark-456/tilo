# services/channels — `tilo-channels`
## Purpose
Cloud Run service (PRD 6.2): email notifications, web push, Email Autopilot (triage, drafting, send), signed email
links. Public ingress for signature-verified webhooks only. WhatsApp is out of scope (SD-01, ADR-0019): no code here emits or reads it.

## Commands
- `uv run --package tilo-channels pytest services/channels`; `just check` from the repo root. Image: `Dockerfile` runs `tilo_channels.app:app` (`/healthz` only, P0-07a).
## Contracts and config
- `packages/contracts-py` event types; writes to `tilo-api` only, never Firestore business state. `config/connectors.yaml`, flags.

## Requirement IDs
- Section 11 (channels, Email Autopilot); SEC-08 (signed webhooks and email links). Built: FR-CHN-07 to -13.

## Local rules
- Webhooks signature-verified, idempotent, ordered per user; forged or replayed rejected. Never send real email
  from dev/CI. Never log bodies, secrets, tokens, nonces or exception messages (types only).
- `triage` (FR-CHN-09; BQ-130 to BQ-138): flag > user label > model suspicious > rule/VIP/mute > model; mail is prompt data only, no tools.
- `links` (FR-CHN-07; BQ-76 to BQ-82): HMAC-SHA256 (`compare_digest`, prefix `tilo-link-v1|`), segments
  alphabet-checked before the MAC; key ring live; nonce consumed last. Answer only plain needs_you cards
  listing email (fail closed); gate, consent, meeting open signed in. HTTP: `answer` needs a POST confirm;
  token in the fragment; verify never consumes; first answer is a compare-and-set on the card.
- `drafting` (FR-CHN-10; BQ-139 to BQ-151): thread raw-capped per field and in total, data only; `drafting_check` gates body, questions.
  `autopilot` (FR-CHN-11; BQ-152 to BQ-158): outbox, policy are ports; any modifier (`autopilot_t3`, safety flag, new recipient, attachment; FR-CHN-12) is T3,
  never scheduled; Edit redrafts at L1. `autopilot_state`: card record before enqueue; a stop is final, queued (`StopQueue`)
  then recorded before any outbox call, never enqueues (revoke, cancel, read in the card's own world; CHN-GATE-A); else `CancelPending`, `sweep()`.
  `autopilot_send` (FR-CHN-13; BQ-182 to BQ-185): `DraftArtifacts` serves the card's text and reply headers; stored flag counts. `autopilot_gate` (CHN-WIRE-1; BQ-225 to BQ-230): L1/T3 `send` needs the owner's `approval.resolved`; authz copied, `check_entry` before the slot; owner = ctor `world_owner` (missing: refuse); `fake_evidence` tests only. `autopilot_policy` (CHN-WIRE-4; BQ-242 to BQ-249): `decide` port; only a clean `run_after_undo` bound to the card is L2; stale (`DECISION_MAX_AGE_S`) or unbound: decide again, else L1; no production adapter yet.
- L2 instruction (BQ-CHRM-2, ADR-0019): `instruction_id` names the owner's `world.requested` (web or mobile web, thread id as
  destination) from the mail card or assistant panel. No inbound message, email included, is ever an instruction.
- `gmail_watch` (FR-CHN-08; BQ-121 to BQ-129): OIDC checked first (verifier, aud, iss, SA, `email_verified is True`): 401/403,
  400 malformed, 2xx unknown address, 500 on failure. History read from the stored cursor, which never moves back; each id
  claimed before triage (a failure keeps the claim); a 404 runs one resync (<= 50 ids). Ids only, never content.
