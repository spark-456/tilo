# ADR-0032 addendum 1: a read-only connection views route on tilo-connectors

- Status: **Proposed**, awaiting the user's approval, like ADR-0032 itself. It adds one route to ADR-0032 decision 2,
  extends HB-02 to it, and adds tickets T1b and T4b. It supersedes BQ-LIVEGAPS-1's default ("wire the broker").
- Deciders: user (approval), supervisor (request, 9 Oct 2026), architect
- Requirement: FR-CON-02, FR-ACC-03, FR-ACC-04, FR-MTG-09; SEC-02; PRD 6.5 (Identity), 11.5, 12.1 (Token broker),
  16.1 rule 2; ADR-0024 (decision 5, consequences), ADR-0032 (decisions 2, 4, 8, 9, HB-06)
- Questions: new BQ-ADR32a-1 and BQ-ADR32a-2. New rule ids HB-08 and HB-09 (they continue ADR-0032's `HB-`).
- Why a separate file: ADR-0032 is on PR #699 (`docs/adr-host-broker-rpc`), not on this branch's base, so an
  "Addendum 1" section in that file would conflict. The merger may fold this file into ADR-0032 as its addendum 1.

## Context
1. PR #740 (`feat/LIVE-GAPS-1b`) adds `GET /v1/connectors` to tilo-api: the signed-in person's registry connectors
   with state, scopes and expiry. It read them through `deps.get_token_broker` and a new
   `TokenBroker.connection_view`. The Opus security review (round 1, head 69782859) failed it. The only production
   wiring of that seam is a `TokenBroker` inside tilo-api, which ADR-0032 rejected (alternative 2, decision 10).
   It asked for an internal read route on tilo-connectors in the ADR-0032 pattern and a read-only seam,
   `deps.get_connection_views`, in tilo-api (BQ-LIVEGAPS-1).
2. What the broker keeps per `(user_id, connector)` record (`tilo_connectors.tokens`). `state` is `connected`, or
   `expired` once Google refused the grant at refresh. A disconnect deletes the record. `scopes` are what Google
   granted. `expires_at` is the access token's expiry (about an hour, refreshed silently). `connected_at` is HB-06's.
   The tokens themselves are a sealed ciphertext with a wrapped key and a nonce. The four plain fields sit beside the
   ciphertext and are bound into its AAD. Reading them needs no KMS call, and an edited value makes the record fail to
   decrypt but still readable as display data.
3. Person grants and the bot grant. A person's Google connectors (`gmail`, `google_drive`, `google_calendar`) share
   one Google grant (CON-D10), so each record may list every scope of that grant. `meeting_host` is the bot account's
   grant, in its own grant group (ADR-0024 decision 5). It is stored under the user id of the person who connected
   it, and only that person hosts with it (ADR-0024, consequences). So `(user_id, meeting_host)` exists for that
   person only.
4. FR-ACC-04 asks for a warning 3 days before a sign-in expires. Keyed on the stored `expires_at`, every connected
   Google connector is permanently "attention" (a #740 review follow-up). The sign-in that does expire is the grant
   itself. PRD 11.5 says sign-ins of an app in Google's testing mode expire after about 7 days, and that grant
   starts at `connected_at`.

## Decision
1. **One route on tilo-connectors**, in the pattern of ADR-0032 decision 2 (POST, a JSON body, ids in the body and
   never in a path or query). It sits under `/internal/connections/` because it covers every connector, not only
   `meeting_host`.

   | Route | Caller in tilo-api | Request | Answer (200) |
   | --- | --- | --- | --- |
   | `/internal/connections/views` | `deps.get_connection_views`, for `GET /v1/connectors` | `user_request` `{user_id}` | `views_answer` `{views: [{connector, state, scopes, connected_at}]}` |

2. **Who may call: HB-01, unchanged.** The same checks in the same order as the meeting-host routes. A missing
   setting is 503 `not_configured`. The ID token is checked next: 401 without a valid one, 502 `not_configured` when
   Google's certificates cannot be had (retryable, never a final 401), and 403 for any account but
   `TILO_MEETING_HOST_CALLER` (tilo-api's). Then come the 64 KiB body cap and the request against the contract (422
   `invalid_request`). The route reuses `TILO_CONNECTORS_AUDIENCE` and `TILO_MEETING_HOST_CALLER`. The second name
   stays although this route is not meeting-host only, because renaming it changes the environment for no gain.
3. **HB-08. Whose views, and what crosses.**
   - tilo-api sends only the signed-in principal's own `user_id` (`Principal.user_id`), never an id from a body,
     path or query (HB-02, extended to this route). Connectors trusts it as it trusts every HB-02 user id (ADR-0032,
     residual trust).
   - Connectors reads only that user's records: `connectors_of(user_id)`, then `get(user_id, connector)`. It is a
     store read only: no token use, no KMS decrypt, no refresh, no provider call, no store write and no event.
     So the answer has no `parts`.
   - Each view is built from an allowlist: `connector`, `state`, `scopes`, `connected_at`. **Never returned:** an
     access or refresh token; the ciphertext, wrapped key or nonce; the OAuth client id or secret; the access
     token's `expires_at`; any account's address (the person's or the bot account's); the record's version; a
     pending revoke from the retry store; another user's record; a connector the registry does not declare.
   - The values are display data. Read without KMS, an edited record can show a wrong state, but it authorises
     nothing. Every token use still decrypts the sealed record, and a send still checks the sealed `connected_at`
     (HB-06).
4. **HB-09. How a view is built.**
   - One view per stored record whose connector `config/connectors.yaml` declares with `auth: oauth2`, in registry
     order, each connector at most once. No record means no view, and tilo-api shows that connector `available`.
   - `state` is `connected` when the stored state is exactly `connected`, else `expired`. The broker writes only
     those two, so anything else is a record it did not write, and it fails toward "connect again" as T3's
     `status` does. There is no `revoked` state: a disconnect deletes the record, and a revoke at Google shows up
     as `expired` at the next refresh.
   - `scopes` are the stored scopes that the registry declares for that connector (the union of its capability
     lists), sorted and unique, and none when `expired`. This shows each connector its own scopes of the shared
     grant. It is also the guard against a stored string that is not a scope. The contract's scope shape is only a
     backstop, because a bare token fits a URL alphabet.
   - `connected_at` is the stored value when the state is `connected` and the value is a contract timestamp, else
     null (`expired`, or a grant from before HB-06 recorded it).
   - Caps in the contract: at most 32 views, 16 scopes per view, and 300 characters per scope from a closed
     alphabet (no query, fragment, user info or space). At those caps an answer stays under 160 KiB, and
     tilo-api's client reads at most 256 KiB.
   - Connectors validates its answer against the contract before sending it (503 when it breaks, as in T3).
     tilo-api's client validates it too, and checks HB-09's order and uniqueness against its own registry. Any
     break makes the whole answer unknown, never partly read.
5. **The bot grant: shown to the person who connected it, to nobody else** (BQ-ADR32a-1).
   `(user_id, meeting_host)` appears in that person's views like any other grant, with its one scope
   `calendar.events.owned`, its state and `connected_at`, and never the bot account's address. Two reasons. That
   person must see that it expired (FR-ACC-04) before a host attempt fails after the gate (BQ-ADR32-1). And
   `GET /v1/connectors` lists `meeting_host` from the registry anyway, so hiding the record would show a connected
   host account as `available`. Nobody else sees it, not even the org's Owner, because no other user's id keys it
   and HB-08 reads only the request's user. Sharing the host account across a team stays a later decision
   (ADR-0024).
6. **tilo-api: the seam and its failure modes.** `deps.get_connection_views` gives a callable
   `(user_id) -> list[view]`. It holds no broker, token-store record, KMS client or secret (SEC-02). It is built from
   `TILO_CONNECTORS_URL` and an ID token for that audience, like `get_meeting_host_client` (decision 8, with its
   30 s negative cache on a failed build), and both may share one client. On every failure, `GET /v1/connectors`
   keeps #740's pinned behaviour: 200, every connector `available`, `state_known` false, and no error text in the
   body, the headers or the logs.

   | Condition | tilo-api |
   | --- | --- |
   | No `TILO_CONNECTORS_URL`, or no ID token (a laptop, dev, CI) | the seam is 503 `not_configured`; the route answers as unwired |
   | 200 with an answer that breaks the contract or HB-09, or one over 256 KiB | unknown as a whole; a fixed log text |
   | 401, 403 or 422 | unknown; logged by status code (a configuration or code defect); not retried |
   | 502 (certificates), 503 (`not_configured`, or Cloud Run's own), a 10 s timeout, a lost connection | unknown; retryable, but not inside the request: the page's next load asks again |

   No call is retried inside one `GET`, so a cold connectors instance costs at most one 10 s wait.
7. **FR-ACC-04 from `connected_at`, not `expires_at`** (BQ-ADR32a-2). The view carries no expiry. tilo-api works
   out when the sign-in expires: `connected_at` plus the sign-in lifetime of the OAuth app (about 7 days in testing
   mode, PRD 11.5). It warns 3 days before that. A re-consent keeps `connected_at` (HB-06), so the warning can come
   early but never late. A connected grant with `connected_at` null gets no warning.
8. **The live gate (ADR-0032 decision 8).** The route builds the broker through the same seam as `status`. So it
   answers 503 `not_configured` wherever the meeting-host routes do: no Firestore store, KMS key, OAuth settings,
   `LIVE=1` or HB-01 variables. It makes no paid call and no Google call. In dev and CI it runs on
   `InMemoryTokenStore` and a fake verifier.
9. **Infra: nothing beyond T5.** tilo-api's `run.invoker` on connectors (decision 9) covers this route. There is no
   new role, because connectors already reads the token store (`datastore.user`) and the route needs no KMS. There
   is no new environment variable either.
10. **Contract.** `contracts/meeting_host_rpc.schema.json` 1.1.0, additive. `$defs/views_answer` and
    `$defs/connection_view` are added and joined to the root `anyOf`. The request is the existing `user_request`.
    The `error` text now names the 502 that T3 already answers. Fixtures are under
    `contracts/fixtures/meeting_host_rpc.views_answer/`.

## Alternatives considered
1. **Wire the broker in tilo-api** (BQ-LIVEGAPS-1's old default). Rejected: SEC-02 and ADR-0032 alternative 2.
2. **Widen `/internal/meeting-host/status` to every connector.** Rejected. `status` is one connector's preflight
   (`scope_ok`) for the host route, and its shape is fixed.
3. **Return `expires_at`.** Rejected. It is the access token's expiry, refreshed silently, so it would flag every
   connected Google connector.
4. **Hide the bot grant from every view.** Rejected (decision 5).
5. **Decrypt each record to authenticate the view.** Rejected. A KMS call per connector per page load buys nothing
   for display data that authorises nothing, and `status` does not decrypt either.
6. **Views as an object keyed by connector id** (unique by construction). Rejected in favour of one obvious list in
   registry order. HB-09's uniqueness is checked on both sides.

## Consequences
- #740 gets real connection state without a broker in tilo-api. SEC-02, the FR-CON-02 import test and
  `security_iam.tftest.hcl` are unchanged.
- Each Connectors page load makes one more internal call: one Firestore list and one read per grant, with no KMS
  call and no paid call.
- Residual trust, as for `status`: a compromised tilo-api could read any user's views. Those are states, scopes
  and connection times, never a token or an address.
- `/v1/connectors`' row field `expires_at` can no longer be the stored access-token expiry. It becomes the derived
  sign-in expiry, or null (BQ-ADR32a-2). #740's tests re-pin it when their override moves to the new seam.

## Tickets
- **T0b.** The user approves this addendum.
- **T1b (architect, this PR).** The contract 1.1.0 with fixtures, codegen and
  `tests/contracts/test_FR_MTG_09_LIVEGAPS_connection_views_contract.py`.
- **T4b (reach-builder, connectors and api; after T3).** It shares T4's client base, and whichever lands first
  builds it. On connectors: the route with HB-01, HB-08 and HB-09, its answer validated. #740's
  `TokenBroker.connection_view` returns the record's state, scopes and `connected_at`, and drops `expires_at`. On
  tilo-api: the client and `deps.get_connection_views`, and #740's route reads through it. The test-writer moves
  #740's override to the new seam and re-pins `expires_at` (BQ-ADR32a-2). Security review.
- **#740 itself** stops reading `deps.get_token_broker` and drops "via `TokenBroker.connection_view`" from
  `services/api/CLAUDE.md`, as its security review asked.
