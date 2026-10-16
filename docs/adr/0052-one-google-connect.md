# ADR-0052: One Google sign-in for a person's Gmail, Calendar and Drive

- Status: **Proposed**. Draft for owner approval; no runtime code depends on this proposal.
- Deciders: owner, security reviewer, connector and API maintainers.
- Date: 17 Oct 2026.
- Requirements: one consent for the three personal Google connectors; keep each connector's access toggle independent; keep the existing one-connector flow and the separate `meeting_host` account.

## Context

The Connectors page currently asks a person to authorize Gmail, Google Calendar and Google Drive separately. They are all Google OAuth connectors, but each uses its own `start_request` and the callback answer describes one connector. The registry already declares the least-privilege scopes for all three. Google supports incremental authorization with `include_granted_scopes=true`; the current flow already uses PKCE, one-time state, redirect checks and a server-held verifier.

The broker's disconnect answer already permits one shared Google grant to revoke all three personal connectors in one provider revoke. The meeting bot is a different Google account and is outside this decision.

## Decision

Add one **Connect Google** start request for exactly `gmail`, `google_calendar` and `google_drive`. The browser sends connector ids only; it cannot choose scopes. The broker resolves each connector's requested scopes from `config/connectors.yaml`, unions and de-duplicates them, then sends one Google authorization request with `include_granted_scopes=true`. The requested union is exactly:

- Gmail: `gmail.readonly`, `gmail.compose`, `gmail.send`.
- Calendar: `calendar.readonly`, `calendar.events.owned`.
- Drive: `drive.file`.

These are the current configured scopes; this ADR adds none. Existing single-connector requests and answers remain valid and unchanged.

The authorization state binds the caller, redirect, PKCE verifier and requested connector set. The callback keeps the current one-use state, caller match, redirect and code-exchange checks. It writes one encrypted Google grant, with the granted scope set, to the token broker. The callback answer has one result per requested connector, each with requested, granted and missing scopes and a state of `connected` or `needs_setup`. A connector is `connected` only when its complete configured scope set is present; partial access remains `needs_setup`. The broker emits `connection.established` only for connectors that are fully connected. No token, account address, client secret or verifier crosses the internal contract.

The Gmail, Calendar and Drive access switches remain separate. A connected OAuth grant does not turn on a connector switch or grant Tilo permission to use that connector. Disconnecting any of these three uses one provider revoke for the shared grant and returns revoked parts for every personal connector it ended. The single-connector connect and disconnect paths remain available. `meeting_host` continues to use its own account, flow and grant.

## Contract draft

`contracts/meeting_host_rpc.schema.json` 1.5.0 adds the three-connector `start_request` variant, a closed list of the six currently configured person-Google scopes, and a multi-connector `callback_answer` variant with per-connector partial-scope records. Existing request and answer variants are retained. New valid and invalid fixtures cover the full set, partial consent, missing connectors and duplicate callback results. Nothing in this draft changes a route implementation or generated consumer type.

## Security and failure behavior

- Reuse the current PKCE verifier, state lifetime, redirect allowlist, authenticated caller binding, one-use callback and no-store/no-log behavior without weakening any check.
- Do not accept caller-supplied scopes. Re-read the registry at start and callback; fail closed if a connector or scope is no longer declared.
- Treat a user-denied consent as the existing `not_granted` result. For a successful but partial grant, record all three outcomes; do not report an incomplete connector as connected.
- Store the provider token once. Connector status rows refer to the same encrypted grant and expose only each connector's granted scopes and state.
- Keep OAuth code and state in the existing callback request only. Do not log or return the authorization code, token response, refresh token, account email or PKCE verifier.
- A revoke timeout follows the existing retryable-revoke behavior; do not mark any connector revoked until the provider confirms, and keep one retry record for the shared grant.

## Consequences

The person accepts the three Google access requests once. All three become connected after full consent; on partial consent, only connectors with all their configured scopes become connected. Existing per-connector switches, status reads, single-connector authorization and meeting-host behavior stay intact. The callback contract grows to report the results separately while the broker stores one provider grant.

Before implementation, the owner and security reviewer should approve this ADR and confirm the broker's encrypted-record key and migration behavior for people who already connected one or more Google connectors separately.

## Focused acceptance cases

1. One Connect Google action produces one authorization redirect whose scope set equals the registry union and includes `include_granted_scopes=true`.
2. Full consent stores one grant and reports all three connectors connected; switches remain independent.
3. If a scope is declined, only connectors with every configured scope are connected; other results say `needs_setup` and list granted and missing scopes.
4. Disconnecting any personal Google connector revokes once and returns revoke results for all three; retry behavior is idempotent.
5. Existing single-connector connect/callback fixtures still validate and keep their current result shape.
6. `meeting_host` cannot appear in the multi-connector request or result.
