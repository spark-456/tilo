# services/channels — `tilo-channels`
## Purpose
Cloud Run service (PRD 6.2): email notifications, web push, Email Autopilot (triage, drafting, send), signed email
links. Public ingress for signature-verified webhooks only. WhatsApp is out of scope (SD-01, ADR-0019): no code here emits or reads it.

## Commands
- `uv run --package tilo-channels pytest services/channels`; `just check` from the repo root. Image: `Dockerfile` runs `tilo_channels.app:app` (`/health` for Cloud Run smoke checks, `/healthz` for in-container probes; P0-07a, P0-07h).
## Contracts and config
- `packages/contracts-py` event types; writes to `tilo-api` only, never Firestore business state. `config/connectors.yaml`, flags.

## Requirement IDs
- Section 11 (channels, Email Autopilot); SEC-08 (signed webhooks and email links). Built: FR-CHN-07 to -13; FR-PA-07 (`plate_reply`, BQ-279 to BQ-284: the Draft reply tap is `Drafter` + `Autopilot.preview` with no instruction, so L1; owner first, reply must answer that mail itself by its Gmail id, never header text (`Drafter.reply_target`, `draft(answers=)`); no send path). `mail_reader`: the production reader shape over the connectors' Gmail read (no connector import, SEC-02).

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
  never scheduled; Edit redrafts at L1; L2 only if the replied-to message is clean, subject too, unique id, DMARC pass from the authserv-id in `config/mail_trust.yaml`, header names matched case-insensitively (`autopilot_inbound`, BQ-274, BQ-278 n; a number word glued to a unit is money, CHN-GATE-F). `participants` (CHN-GATE-E, ADR-0025): `Autopilot._card` fills `DraftContext.participants` from its own reader (a caller's value is dropped); names only from BASE address local parts (no display name, no plus tag), filtered, capped 100 x 8, in memory for one card; `t3_content_signal(body, names=)` takes the draft's own To/Cc and mailbox names, none fails closed. `autopilot_state`: card record before enqueue; a stop is final, queued (`StopQueue`)
  then recorded before any outbox call, never enqueues (revoke, cancel, read in the card's own world; CHN-GATE-A); else `CancelPending`, `sweep()`.
  `autopilot_send` (FR-CHN-13; BQ-182 to BQ-185): `DraftArtifacts` serves the card's text and reply headers; stored flag counts. `autopilot_gate` (CHN-WIRE-1; BQ-225 to BQ-230): L1/T3 `send` needs the owner's `approval.resolved`; authz copied, `check_entry` before the slot; owner = ctor `world_owner` (missing: refuse); `fake_evidence` tests only. `autopilot_policy` (CHN-WIRE-4; BQ-242 to BQ-249): `decide` port; only a clean `run_after_undo` bound to the card is L2; stale (`DECISION_MAX_AGE_S`) or unbound: decide again, else L1; no production adapter yet.
- L2 instruction (BQ-CHRM-2, ADR-0019): `instruction_id` names the owner's `world.requested` (web or mobile web, thread id as
  destination) from the mail card or assistant panel. No inbound message, email included, is ever an instruction.
- `reschedule_intent` (FR-CAL-07 b; BQ-CAL07B-3, -4): `detect_move_request(mail)` is rules only (lists in `config/move_request.yaml`), no model, no sender read, bounded scan; triage adds a `move_request` marker (kind, constraint) to `needs_reply` results only.
- `gmail_watch` (FR-CHN-08; BQ-121 to BQ-129): OIDC checked first (verifier, aud, iss, SA, `email_verified is True`): 401/403,
  400 malformed, 2xx unknown address, 500 on failure. History read from the stored cursor, which never moves back; each id
  claimed before triage (a failure keeps the claim); a 404 runs one resync (<= 50 ids). Ids only, never content.
- `meeting_followup` (FR-MTG-08, -08b, -08c; BQ-MTG08-1 to -8, BQ-MTG08B-1 to -6, BQ-MTG08C-1 to -7): only the meeting Owner, after the Owner confirmed the minutes; recipients from the directory port only; content is the confirmed summary, verified decisions and open items; `Checker` with no instruction (a commitment word only inside a verbatim confirmed entry) plus an unconfirmed-text refusal; schema caps, `flagged is not False`; a commitment-word entry is a verbatim repeat only after a label lead-in; bounded NFKD, overlay marks flagged; thread-less `new` card via `Autopilot.preview` (T3, L1); no send path. tilo-api wiring checklist: `tests/API_FR_MTG_08.md`.
- `digest` (FR-CHN-18; BQ-CHN18-1): 24 h window of world-scoped L2/L3 `policy.applied` actions + user FYI mail; contract-validated fields; signed single-use `LinkService` Undo/Report links; empty day sends nothing; stores digest artifact, asks `DigestPolicyPort` (`send_email` to trusted `mailbox(user_id)` at L3), emits `policy.applied`, and enqueues once per UTC day via `autopilot_state.enqueue_digest`.
- `web_push` (FR-CHN-17; BQ-CHN17-1 to -3): `SubscriptionStore` keeps a person's browser subscriptions (https, <= 2048, push-service host allowlist, <= 5 each, `config/web_push.yaml`); `PushNotifier.notify` reads settings and quiet hours first (a gate is never hidden: `in_app` always true), then `send_push` (T1) goes policy L3 -> `enqueue_digest` -> outbox; only `WebPushAdapter` (outbox grant) calls the `PushSender` port. VAPID is the secret NAME `webpush-vapid-private-key`; the module logs nothing and imports no HTTP client or connector. API: `tests/API_FR_CHN_17.md`.
- `web_push_sender` (FR-CHN-17b; BQ-CHN17b-1): the production `PushSender` over pywebpush (MPL-2.0, `docs/licences.md`): `production_sender()` is None unless `K_SERVICE`, the mounted secret value (`WEBPUSH_VAPID_PRIVATE_KEY`, from the secret NAME) and `TILO_WEBPUSH_VAPID_SUBJECT` are all set; 404/410 = `SubscriptionGone`, anything else `PushUndelivered`, no vendor text. tilo-api owns subscriptions (`push_routes`); channels reading them is not wired.
