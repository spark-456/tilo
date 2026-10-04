# services/channels — `tilo-channels`
## Purpose
Cloud Run service (PRD 6.2): WhatsApp webhook and sender, email notifications, web push,
channel identity binding, Email Autopilot triage. Public ingress for signature-verified webhooks only.

## Commands
- `uv run --package tilo-channels pytest services/channels`; `just check` from the repo root.

## Contracts and config
- `packages/contracts-py` event types; writes to `tilo-api` only, never to Firestore business state.
- `config/connectors.yaml` (channel routing), feature flags.

## Requirement IDs
- Section 11 (channels, Email Autopilot); SEC-06 (binding, T3 PIN), SEC-08 (signed webhooks and email links). Built: FR-CHN-02, -03, -05 to -11.

## Local rules
- Webhooks signature-verified, idempotent, ordered per user; forged or replayed rejected. Never send real email or WhatsApp
  from dev/CI. Never log bodies, secrets, tokens, nonces, full numbers (`mask_number`: last 4) or exception messages (types only).
- `whatsapp`: HMAC over raw bytes, dedupe via `DedupeStore.claim`, serialised per sender. Stale (> 300 s old or > 60 s ahead)
  claims nothing. Duplicate 200 "duplicate"; forged/missing signature 401; signed non-JSON 400; handler raises: claim kept
  (at-most-once), 200 "failed". App secret >= 32 B; wamids never logged (`message_ref`); object, field, `phone_number_id` pinned.
- `keywords`: whole-message, case-insensitive, bound numbers only; control-plane effect, then one confirmation or "Could not apply that".
  `inbound`: unbound -> opt-in text (`opt_in_allowed` limits it); bound -> keywords, cards, else `off_topic` (fixed redirect, no model).
- `triage` (FR-CHN-09; BQ-130 to BQ-138): flag > user label > model suspicious > rule/VIP/mute > model; mail is prompt data only, no tools.
- `links` (FR-CHN-07; BQ-76 to BQ-82): HMAC-SHA256 (`compare_digest`, prefix `tilo-link-v1|`), segments
  alphabet-checked before the MAC; key ring live; nonce consumed last. Answer only plain needs_you cards
  listing email (fail closed); gate, consent, meeting open signed in. HTTP: `answer` needs a POST confirm;
  token in the fragment; verify never consumes; first answer is a compare-and-set on the card.
- `binding` (FR-CHN-03; BQ-89): number via cipher, HMAC lookup (key >= 32 B); code HMAC, 6 digits, 10 min,
  5 atomic `try:` slots (kept when replaced); bound while `num:`/`user:` agree, < 30 d. SEC-10 caps only
  with `send_caps=SEND_CAPS` (unknown keys: ValueError; user window first; holder exempt from the number cap).
- `cards` (FR-CHN-05; BQ-89): random button ids; a tap counts only from the card's bound number; T3 approve
  needs the PIN (next text within 300 s, one try; digits in the next 300 s are `pin_late`, never routed);
  Hold/Edit keep a gate open (repeats: one event); one send per card id; emits `channel.message_out`/`_in`.
- `drafting` (FR-CHN-10; BQ-139 to BQ-151): thread raw-capped per field and in total, data only; `drafting_check` gates body, questions.
  `autopilot` (FR-CHN-11; BQ-152 to BQ-158): outbox and policy are ports; any modifier (`autopilot_t3` signal on the raw body,
  safety flag, unknown recipient) is T3, never scheduled; only an instructed T2 draft rides the 60 s window; Edit redrafts at L1.
- `gmail_watch` (FR-CHN-08; BQ-121 to BQ-129): OIDC checked first (verifier, aud, iss, SA, `email_verified is True`): 401/403,
  400 malformed, 2xx unknown address, 500 on failure. History read from the stored cursor, which never moves back; each id
  claimed before triage (a failure keeps the claim); a 404 runs one resync (<= 50 ids). Ids only, never content.
