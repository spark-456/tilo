# ADR-0045: Signed, single-use team invitation links

- Status: **Proposed** (design only; owner approval is pending).
- Requirement: INVITE-LINK.
- Deciders: product owner; architect for contract and security shape.
- Related: ADR-0044, PE-02, PE-17, PE-20, PE-37.

This document proposes a design only. No contract or product-owner approval is implied. Implementation must wait for the owner’s approval relayed by the Claude supervisor.

## Decision requested

Add an expiring bearer link that a signed-in person can redeem once to join one team. The link is a capability to request membership, not a login credential and not an authorization claim. Redemption requires a verified, full web or mobile-web session and applies the existing team membership rules. A link never grants access merely because its signature is valid.

This extends ADR-0044’s accepted-invitation path. It does not change team lead powers, membership visibility, world sharing, or the rule that the invitee must accept. It produces no world event. Existing directory-write logging remains ids-only.

## Threat model and controls

| Threat | Control |
| --- | --- |
| Forged or edited team, org, expiry, or inviter claims | HMAC-SHA-256 over a fixed, versioned ASCII token format with domain separation; reject unknown key ids, malformed fields, and non-constant-time signature comparisons. Then independently load and validate the stored invitation. |
| Link copied, leaked, or forwarded | Treat the URL as a bearer secret. Require a verified full session; reveal no roster or private team data before acceptance. A forwarded link can be used by whoever redeems first, so creation UI must say this plainly. |
| Replay or two people redeeming concurrently | Persist one `pending` state and consume it in the same durable transaction that adds the membership. A transaction/CAS winner is the sole redeemer. No membership write occurs if consumption loses. A replay returns the same generic unavailable response and cannot add another membership. |
| Expired or revoked token | Check server time against stored `expires_at` at redemption. Revocation atomically changes `pending` to `revoked`; expiry is derived and need not be swept. Both fail closed. |
| Creator loses lead authority, then later becomes a lead again | On redemption, re-evaluate the creator’s lead authority at both the invite’s `created_by.at` and current server time using the whole stored org directory. The new lead entry cannot retroactively authorize an old invite. If the creator was an org owner at issuance, require current owner authority or apply the separately specified owner-assignment rule. |
| Cross-org use, non-member target, or membership-slot exhaustion | Bind the signed claims and stored record to `org_id`; require the authenticated person’s stored record to be in that org. Enforce the existing maximum of eight stored memberships before consumption. Refuse demo, email-link, world-bound, and other partial sessions. |
| Token exposure through storage, logs, analytics, or referrer headers | Persist only SHA-256 of the random nonce, never the URL/token. Return the raw link once at creation; do not offer a read-back. Redact request bodies and URL fragments; do not put the token in query strings. The landing page reads a URL fragment, immediately clears it from browser history, and POSTs it over TLS with `Referrer-Policy: no-referrer`. |
| Key rotation or algorithm confusion | Fix the algorithm and token version in code; include a bounded `kid` for a configured HMAC key ring. Retain verification keys until all links signed by them expire or are revoked. Never select an algorithm from token input. |
| CSRF or link-preview bots consuming a link | Redemption is an authenticated POST with normal CSRF/origin protections; GET and page preview never consume. Link scanners cannot redeem without a full signed-in session and an explicit user action. |

Assumptions: TLS is enforced; HMAC keys are supplied by the existing secret configuration path and are not stored in Firestore, source, logs, or fixtures. XSS in the signed-in client can steal a displayed token and is outside the link protocol’s protection. Use the existing write limit and cap active links per team; do not introduce paid services.

## Token and stored state

Token format is fixed and ASCII, with base64url without padding for the nonce and signature:

```text
v1.<kid>.<invite_id>.<org_id>.<team_id>.<issued_unix>.<expires_unix>.<nonce_b64url>.<signature_b64url>
```

`nonce` is 32 CSPRNG bytes. `signature` is `HMAC-SHA-256(key[kid], b"tilo.team-invite-link.v1\0" + ASCII(all fields before signature))`. `issued_unix` is the server time represented by `created_by.at`; `expires_unix` is the server-computed `expires_at`. Parsing is closed and rejects duplicate separators, non-canonical encodings, integer overflow, unknown versions, and unknown key ids. Compare `SHA-256(nonce)` to the stored digest after signature validation.

The server stores one invitation record with `status: pending | redeemed | revoked`. Expiry is `status == pending && now >= expires_at`; expired records are unusable even if cleanup never runs. Only the acceptance transaction may move `pending` to `redeemed`; only an authorized lead/owner may move `pending` to `revoked`. Terminal states never return to pending. Revoking an already redeemed link does not remove the accepted member; removing that member uses the existing remove-member operation.

For a link created by a team lead, the resulting person membership records the link creator in `assigned_by`, `accepted_at` from the redemption transaction, and the link id. It counts only when the existing PE-02 invitation rules hold. For a link created by an org owner, the owner-assignment rule applies, but redemption still identifies the person and records their explicit acceptance before membership is written. These rules must not allow a lead to set `lead: true`, change org roles, or affect another team.

## API proposal

All bodies are closed JSON; writes use the existing rate limit, replay-only refusal, compare-and-set discipline, and full-session rules. Do not add a GET endpoint that accepts or consumes a token.

### Create

`POST /v1/teams/{team}/invite-links`

- Allowed to a lead of this team or an org owner in a full web/mobile-web session.
- Request: `{ "expires_in_seconds": 604800 }`; optional, default 604800, accepted range 3600–2592000. The server computes the absolute expiry and caps active pending links per team at 100.
- Response `201`: `{ "invite_id": "til_<24 lowercase hex>", "team": "tm_…", "invite_url": "https://<configured-origin>/join#<token>", "expires_at": "<timestamp>" }`.
- Return the URL only in this response. Logs, errors, metrics, list results, and stored records contain no token or nonce.

### List and revoke

- `GET /v1/teams/{team}/invite-links`: lead/owner only; returns ids, creator id, created/expiry timestamps and derived status (`pending`, `expired`, `redeemed`, `revoked`). Never returns a token, digest, or nonce.
- `DELETE /v1/teams/{team}/invite-links/{invite_id}`: lead/owner only; CAS `pending` to `revoked` with `revoked_by` and server `revoked_at`. Return `204` for a successful revoke. For unknown, foreign-team, already-redeemed, or already-revoked ids, use a uniform not-found/unavailable response so this endpoint does not become an invitation-state oracle.

### Accept

`POST /v1/team-invite-links/accept`

- Request: `{ "token": "<complete signed token>" }`; token is in the POST body, never a query or route parameter.
- Require a full, non-demo, non-world-bound web/mobile-web session and an existing self-joined person record in the invite’s org. Self-join, if needed, is a separate existing flow.
- In one durable transaction: verify signature and stored record; check org/team, expiry, pending status, token digest, inviter authority, and the person’s membership limit; consume the invite and append the membership with server-generated stamps. The transaction must include both the invitation record and person record. If current stores cannot provide this atomicity, implementation must stop and return to design review rather than claim single-use semantics from two independent writes.
- Success `200`: `{ "team": "tm_…", "state": "member", "accepted_at": "<timestamp>" }`.
- Every invalid, expired, revoked, already-used, wrong-org, stale-inviter, or bad-signature token returns the same generic `404 {"detail":"invite_unavailable"}`. Capacity exhaustion returns a generic `409 {"detail":"membership_limit"}` without consuming the token. Do not echo the token, team details, or whether a user/team exists.

## Exact proposed contract changes (not applied)

1. Add `contracts/team_invite_link.schema.json`, version `1.0.0`, a closed object with required fields:
   - `id`: `^til_[0-9a-f]{24}$` (96 random bits);
   - `org_id`: `common.schema.json#/$defs/org_id`;
   - `team`: `common.schema.json#/$defs/team_id`;
   - `created_by`: `team_lead.schema.json#/$defs/assignment`;
   - `expires_at`: `common.schema.json#/$defs/timestamp`;
   - `nonce_sha256`: lowercase 64-hex SHA-256 digest;
   - `key_id`: 1–32 lowercase ASCII letters, digits, `_` or `-`;
   - `status`: `pending | redeemed | revoked`.
   Conditional fields: `redeemed_by` (`user_id`) and `redeemed_at` (timestamp) are required only for `redeemed`; `revoked_by` (`user_id`) and `revoked_at` are required only for `revoked`; forbid the other terminal-state fields. For `pending`, forbid both pairs. The schema stores no raw token, nonce, signature, or URL. Cross-record checks enforce `created_by.at < expires_at`, `redeemed_at < expires_at`, org/team identity, terminal transitions, and creator authority.
2. Bump `contracts/person.schema.json` from `1.1.0` to `1.2.0` by adding optional `invite_link_id` to `$defs.membership`, using the same `^til_[0-9a-f]{24}$` format. Existing people and fixtures remain valid. If present, cross-record validation requires the referenced invite record to be redeemed for the same org, team, and person; `assigned_by` equals the invite’s `created_by`; and `accepted_at` equals `redeemed_at`. Membership without this field keeps the existing PE-02 rules.
3. Amend `contracts/people.rules.md`: PE-02 adds a link-invited membership as an accepted invitation whose creator was authorized when the link was issued and at acceptance; the `invite_link_id` cross-reference above is required when the membership was created from a link. PE-37 adds create/list/revoke/redeem actions, authorized actors, server stamps, single-use transaction semantics, and the no-revival rule. Add PE-38 defining link expiry, token privacy, single-use state transitions, and the generic failure response. Keep the existing “no new event” rule.
4. No event registry/schema, `docs/prd/`, world-share, or team-lead contract changes are proposed.

## Acceptance tests (names include `INVITE_LINK`)

- `test_INVITE_LINK_create_requires_current_team_lead_or_org_owner_and_full_session`
- `test_INVITE_LINK_create_returns_secret_once_and_never_persists_or_logs_it`
- `test_INVITE_LINK_create_enforces_expiry_bounds_and_active_link_cap`
- `test_INVITE_LINK_tampered_unknown_kid_noncanonical_and_wrong_org_tokens_fail_generically`
- `test_INVITE_LINK_expired_and_revoked_links_cannot_be_redeemed`
- `test_INVITE_LINK_accept_requires_explicit_full_session_and_existing_org_person`
- `test_INVITE_LINK_accept_atomically_consumes_and_adds_one_membership`
- `test_INVITE_LINK_concurrent_redeemers_have_exactly_one_winner`
- `test_INVITE_LINK_replay_never_duplicates_or_changes_membership`
- `test_INVITE_LINK_failed_membership_limit_does_not_consume_link`
- `test_INVITE_LINK_creator_must_be_authorized_at_issue_and_redemption_and_rejoin_does_not_revive_link`
- `test_INVITE_LINK_revoking_redeemed_link_does_not_remove_member_but_member_removal_does`
- `test_INVITE_LINK_contract_rejects_raw_secret_and_invalid_terminal_state_fields`
- `test_INVITE_LINK_membership_crossref_matches_redeemed_invite_and_acceptance_stamp`
- `test_INVITE_LINK_existing_membership_fixtures_remain_valid_after_person_schema_1_2_0`

## Approval gate and implementation dependency

The product owner must approve the proposed contract changes, relayed by the Claude supervisor, before any schema/rules edits or contract-dependent code. After approval, an implementation ticket should assign the atomic transaction boundary and storage adapter explicitly. This lane does not implement that work or start a separate data-gap ticket without direct assignment.
