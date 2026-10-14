# Proposed ADR: provider-specific partner OAuth consent

Status: **Proposed; awaiting user approval of the frozen-contract change.**
Date: 2026-10-14. Ticket: PREP-PARTNER-CONSENT-ADR.
Baseline inspected locally: cached `origin/codex/merge-b-oldui` at
`d8f3ae4d0005cce58d39d5e6f6a6e0e5597d8f23`.

## Decision requested

Approve a narrow, provider-specific extension of the existing consent boundary:
Canva first, Slack next, while retaining the Google flow and its safeguards.
Approval would authorize a separately reviewed contract/code implementation;
it would not authorize app installation, catalogue activation, credentials,
network calls, sending, deployment, or enabling any partner flag.

This draft changes no contract or executable code. PREP-CANVA-2 remains BLOCKED.
PREP must not fold before actual GATE-OLDUI LIVE. The partner tiles remain a
separate local change at `143f1916`, with their existing 152-pass proof retained.

## Context and exact boundary

`contracts/meeting_host_rpc.schema.json` is currently version 1.3.0.
`$defs.start_answer` is closed and requires only `authorize_url`. Its value is
null when no scopes are missing, or a string of at most 2048 characters matching:

```text
^https://accounts\.google\.com/o/oauth2/v2/auth\?[A-Za-z0-9%._~&=+-]+$
```

The same definition rejects newlines and query fields named `client_secret`,
`code_verifier`, `code`, `access_token`, or `refresh_token`. A generic HTTPS URL
would lose the current closed endpoint boundary and is not proposed.

`services/connectors/src/tilo_connectors/consent.py` also assumes Google:
`AUTH_URL`, `_ACCESS_LINE`, one `OAuthSettings`, Google authorization parameters,
the imported Google `TOKEN_URL`, a Google refusal message, and Google grant
handling in `_discard`. `_Flow` binds user, connector, card, verifier, expiry,
and requested scope descriptions, but has no explicit provider identity.
The broker's `tokens.py` defaults connectors into the shared `person` grant
group; assigning partners to that default would mix unrelated provider grants.

## Proposed contract change

Keep the existing closed response shape, `string | null`, length bound, encoded
query character set, and secret-name exclusions. Replace only the Google URL
branch with an explicit union of provider endpoint branches. Update the
Google-only descriptions of start/callback credentials to explain provider
selection from the server's bound flow. Bump the contract version under the
repository's contract-change process and regenerate Python/TypeScript outputs
after approval; do not hand-edit generated validators.

| Provider | Exact proposed authorization origin and path | Stage |
| --- | --- | --- |
| Google | `https://accounts.google.com/o/oauth2/v2/auth` | Preserve |
| Canva | `https://www.canva.com/api/oauth/authorize` | First |
| Slack | `https://slack.com/oauth/v2/authorize` | Next, verification gate |

Each branch must match the complete HTTPS endpoint followed by `?` and the
existing encoded query shape. No subdomains, suffix matching, userinfo, ports,
fragments, alternative paths, caller-supplied endpoints, or arbitrary redirects.
Retain the existing null behavior and request/answer required-property sets.
Provider identity is server-owned: API/client validation must cross-check the
returned endpoint against the requested connector, beyond schema validation.

These partner endpoints are proposed design inputs, not provider capability
verification. No external documentation or provider was contacted in this PREP.
Before implementation, verify exact authorize/token/revoke endpoints, scopes,
PKCE support, response shape, refresh semantics and account/workspace identity
against official documentation for the owner's actual app type. Any deviation
from this endpoint list returns for review instead of broadening the allowlist.

## Proposed implementation boundary after approval

Introduce a closed server-owned provider profile selected from connector
identity. It owns authorization/token/revocation endpoints, OAuth settings,
scope serialization, consent copy, token response normalization, refresh and
revocation behavior. Unknown, disabled or incompletely configured profiles fail
closed before a flow or URL is minted. Do not infer a profile from a callback
parameter or a model response. The callback RPC can keep its current shape:
the one-time state retrieves the provider-bound flow.

Keep Google's `access_type`, `prompt`, and `include_granted_scopes` behavior in
its profile. Canva gets its own settings and capability-to-scope declarations.
Slack gets a separate profile with explicit bot/user scope handling and a
validated workspace identity; do not apply Google's space-separated scope or
flat token-response assumptions to Slack. Keep access/password copy specific
to the selected provider without changing frozen consent card choices,
safe-default Hold, or web/mobile-only person approval.

Extend `_Flow` to bind provider, connector, person, card, redirect URI, requested
scopes, and expiry to the PKCE verifier. Bind the workspace/org context in the
authenticated route layer and verify it again on callback. Capture the profile
and redirect URI at start so changes cannot redirect an in-flight exchange.
Token exchange uses an injected fake/replay transport in tests and the selected
profile's fixed endpoint. Validate granted scopes and provider identity before
storage; an omitted scope field must not silently count as all access granted.

Separate broker grant identities by provider and account/workspace as well as
connector grant group. Preserve Google's existing shared-grant and meeting-bot
rules. A Canva or Slack disconnect/discard/refresh must never revoke a Google
grant or another Slack workspace's grant. Review broker settings, refresh,
discard, delete-user and retry-revoke paths together before enabling partners.
No token, secret, verifier or code may enter cards, logs, events, reprs or URLs.
Keep tokens sealed and available only inside the connector broker/adapter seam.

## PKCE, state and consent rules

- Retain cryptographically random state and the existing 600-second, single-use
  lifetime; atomically spend state on first callback, including invalid attempts.
- Retain S256 PKCE and server-only verifiers. Never use plain PKCE or put a
  verifier/client secret in an authorization URL. Canva must pass the PKCE gate.
- Verify Slack's chosen app flow supports S256 before implementing it. If it
  does not, leave Slack blocked and request a separate reviewed decision;
  this ADR does not approve falling back to a weaker flow.
- Reject wrong person/provider/connector/workspace, expired or replayed state,
  denial, missing code, mismatched redirect and unrequested scopes before
  storing tokens or emitting a successful connection event.
- Preserve the per-user flow cap and the current in-memory single-instance
  limitation. This proposal does not authorize storage/infra changes to remove it.
- Request only capability-declared missing scopes; render their exact access
  descriptions before the person's Connect. Building a card/URL grants nothing.
- OAuth consent is separate from action approval. Exports, uploads and Slack
  sends still require outbox + deterministic policy + the person's T3 approval
  for the exact payload. Recorded artifact provenance/world events follow actual
  completed work; no success event or animation follows a URL alone.

## Tests to add after approval

1. Contract fixtures: valid Google/Canva/Slack URLs and null; retain all existing
   Google positives, length limits, secret exclusions and closed-object tests.
   Reject HTTP, lookalike hosts, userinfo, ports, wrong paths, fragments, control
   characters, raw spaces and empty queries for every branch. Test encoded,
   duplicate and case-varied secret parameter names in parsed runtime validation.
2. Strengthen
   `tests/contracts/test_FR_CON_02_ADR35_L1_live_connector_routes_contract.py`
   for the explicit approved union while retaining its Google and secret/2048
   assertions. Preserve the closed response tests in
   `test_FR_MTG_09_meeting_host_rpc_contract.py`; regenerate and exercise both
   language validators against the same fixtures.
3. Extend `services/connectors/tests/test_FR_CON_03_consent_card.py` with fake
   provider profiles: provider copy, exact endpoint/parameters, S256 challenge,
   incremental scopes, null without a flow and refusal before profile readiness.
4. Mock callback tests: correct token endpoint/redirect, single-use state,
   wrong person/provider/connector/workspace, expiry, replay, denial, missing
   code, partial/extra grants, malformed token responses and storage failure.
   Assert no token save or success event on refusals; assert no credential leak.
5. Fake broker tests: Google shared grants unchanged; isolated Canva and Slack
   workspace grant records; refresh/revoke/discard/delete-user failure retries
   cannot cross provider boundaries or leave a falsely connected status.
6. API/web mocked start-to-callback tests: endpoint/connector mismatch refused,
   Google flow unchanged, unconfigured partner honest and inert. Fake Canva
   export and Slack send require exact T3 approval/outbox policy; no dispatch
   occurs from consent alone. Pin artifact provenance and recorded event output.

All implementation tests use fakes or recordings, with no real authorization,
tokens, network, provider calls or sends. No tests were run for this draft and
no previously passed QA2/QA11/SKILLS/tiles proof was repeated.

## Rollout and alternatives

After user approval, land reviewed contract fixtures/validators and provider
isolation first, then Canva implementation and its fake end-to-end tests, then
Slack only after its capability gate. Owner app readiness and a separate
activation authorization remain prerequisites; config/catalogue/routes/flags
stay unchanged throughout this PREP. Do not fold PREP until actual OLDUI LIVE.

Keeping Google-only consent is the current safe behavior and leaves partners
parked. A generic URL allowlist or reusing Google's broker identity would
increase the trust boundary; both are rejected by this proposal. Partner-specific
RPCs could isolate schemas further, but would add routes and duplicate consent
plumbing; reconsider them if provider semantics cannot fit the current closed
start/callback exchange without additional frozen-contract changes.
