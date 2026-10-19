# ADR-0032: The meeting-host token broker stays in tilo-connectors; tilo-api reaches it over an internal RPC

- Status: Accepted (user approved 8 Oct 2026, in the supervisor chat, including the infra test change in decision 9).
  It amends ADR-0024 (which service runs the `meeting_host` adapter's token use) and supersedes BQ-MTG09-21.
  Ticket T1 adds one contract and T5 changes `infra/`. The merger may renumber.
- Deciders: user (approval, including the infra test change in decision 9), supervisor (the choice), architect
- Requirement: FR-MTG-09; SEC-02, SEC-03, SEC-11, SEC-12; FR-CON-02; EFF-01; PRD 6.1, 6.5 (Identity), 12.1 (Token
  broker), 15, 16.1 rule 2; CON-D9, CON-D10; ADR-0002 decision 11, ADR-0024 (decision 4, amendment 4), ADR-0026
- Questions: supersedes BQ-MTG09-21, extends BQ-MTG09-23; new BQ-ADR32-1. New rule ids HB-01 to HB-07 (host
  broker; no other prefix in the repo uses `HB-`).

## Context
1. ADR-0024 makes `meeting_host` a connector with one action, `create_meeting_event` (T3, always a person).
   BQ-MTG09-21 had the host route build `MeetingHostAdapter` inside tilo-api from two seams,
   `deps.get_token_broker` and `deps.get_meeting_host_transport`. Neither the BQ nor ADR-0024 said which service
   decrypts the bot account's grant.
2. MTG-WIRE-1 (`feat/MTG-WIRE-1`, head 0bde0544, `services/api/src/tilo_api/host_wiring.py`) filled both seams in
   tilo-api: a `TokenBroker` over `CloudKms`, a `FirestoreTokenStore` and the OAuth client secret. The Opus security
   review failed it. PRD 6.5 says "Only `tilo-connectors` can decrypt OAuth tokens", and 12.1, 16.1 rule 2 and
   SEC-02 say the same. `services/connectors/tests/test_FR_CON_02_secrecy.py::test_FR_CON_02_no_service_outside_tilo_connectors_imports_the_broker`
   fails. `infra/envs/dev/tests/security_iam.tftest.hcl` allows exactly one decrypter on `oauth-tokens` (the
   connectors account) and gives `workspace-oauth-client` to connectors only, and `infra/ACCESS.md` section 9 lists
   "tilo-api: decrypt on `oauth-tokens`" as not granted on purpose. Deployed, that broker could not even work.
3. What runs where today. The host run is an in-process thread in tilo-api (ADR-0026 context 3). Its outbox is
   tilo-api's (`InMemoryOutboxStore`), which calls the adapter's `execute_side_effect(entry, grant)` and ignores
   what it returns. The adapter reads the pinned draft from the run's artifact store and writes the receipt
   artifact (`_Drafts`, `_Receipts` in `tilo_api.meeting_host`). tilo-api has VPC egress (`ALL_TRAFFIC`) and
   already calls the internal harness directly. tilo-connectors is internal-only, invoked only by tilo-harness
   (`cloud_run.tftest.hcl`), and serves no route but `/health`.
4. The pattern to reuse. Channels' `mail_reader` takes the connectors' Gmail read as a Protocol whose production
   implementation is "an RPC client to tilo-connectors, never `GmailAdapter` in-process (SEC-02)". That client is
   not built, and ACCESS.md 8.1 says channels never reaches connectors. Service-to-service identity is built three
   times already, with no shared secret: a Google-signed OIDC ID token, audience equal to the callee's URL, the one
   allowed caller account read from the callee's own environment, `email_verified` true (the schedule tick in
   tilo-api, the harness tick, the channels Gmail push).

## Decision
1. **Where things live.** tilo-connectors keeps the `TokenBroker`, the token store, the KMS client, the OAuth
   client secret, the live Google transport and every token use of `MeetingHostAdapter`. tilo-api keeps the run,
   the gate, its outbox (which writes the world's one `data.transfer`), the draft and receipt artifacts and
   `on_connection_event`. No module under `services/` other than `services/connectors` imports
   `tilo_connectors.tokens`, `tilo_connectors.live` or `tilo_connectors.adapters`. tilo-api may keep the pure
   modules it uses (`tilo_connectors.meeting_host`, `Outbox`, `provenance`, `registry`). One seam,
   `deps.get_meeting_host_client`, replaces BQ-MTG09-21's two.
2. **The surface: three routes on tilo-connectors.** Each is POST with a JSON body, and ids travel in the body,
   never in a path or query.

   | Route | Caller in tilo-api | Request | Answer (200) |
   | --- | --- | --- | --- |
   | `/internal/meeting-host/send` | the host run's outbox, through the stub (decision 6) | `entry` (`outbox.schema.json`, in its enqueued state `queued`); `evidence` (the crossref case tilo-api's own enqueue checked: `reserved_by`, `authorised_by`, `world_owner`, the rest null or empty); `draft` `{artifact_id, version, content_sha256, content_b64}` | `outcome`: `sent`, `refused`, `possibly_sent` or `retry`; `receipt` (only when sent) `{world_id, outbox_id, meeting_id, owner, draft: {artifact_id, version}, event_ref, conference}`; `may_have_sent` (only with `retry`); `parts` |
   | `/internal/meeting-host/status` | the host route's preflight; the owner's connection view | `user_id` | `state`: `connected`, `expired` or `none`; `scope_ok` |
   | `/internal/meeting-host/disconnect` | the owner's disconnect (decision 7) | `user_id` | `revoked_at_provider`; `parts` |

   `parts` lists what the broker emitted during that call: `connection.*` as `{type, connector, user_id}` and
   `alert.raised` as its alert id, nothing more. A fourth route is reserved for ADR-0024 amendment 4 (accepted by
   the user on 8 Oct 2026, PR #678) and is built in that amendment's own ticket, not here:
   `/internal/meeting-host/join-link`, `{user_id, event_ref}` (the receipt's) to `{join_url}`. Its answer is the only
   one on this surface that carries a Meet link, under MJ-04 to MJ-06 on both hops. Connecting the bot account
   (the consent code exchange) is not on this surface (BQ-ADR32-1).
3. **What never crosses.** No request, answer, error or log line on either side carries an access or refresh
   token, the client secret, key material or a Meet link (except the reserved join-link answer). Both directions
   validate a closed schema. T1 adds it as `contracts/meeting_host_rpc.schema.json`, because PRD 15 and ADR-0002
   decision 11 make every structure that crosses a service boundary a contract. Errors are fixed codes. The draft
   crosses because connectors cannot read the run's artifact store (it has no `artifacts` bucket role, ACCESS.md
   section 2) and the Google call needs its title, times and invitees. It is the pinned item the owner approved,
   bound by hash.
4. **Caller identity and who may call.**
   - **HB-01.** tilo-api sends `Authorization: Bearer <ID token>`, minted for its own runtime account from the
     metadata server (google-auth `fetch_id_token`, audience equal to the connectors URL). Cloud Run checks
     `run.invoker` first (decision 9 adds tilo-api beside harness). Then every `/internal/meeting-host/*` route
     verifies the token itself before it reads the body: a Google issuer, `aud` equal to
     `TILO_CONNECTORS_AUDIENCE`, `email` equal to `TILO_MEETING_HOST_CALLER` (tilo-api's account) and
     `email_verified` true. A malformed token is refused before any certificate fetch. The answer is 401 without
     a valid token, 403 for every other account (tilo-harness included, which also holds `run.invoker`) and 503
     `not_configured` when either variable is unset. Both values come from the service's environment, never from
     the request. There is no shared secret and no API key.
   - **HB-02.** Inside tilo-api, only the host run's outbox stub calls `send`. `status` and `disconnect` take only
     the signed-in principal's own user id (`w.actor`), never an id from a body, path or query. A send names no
     user: the grant it uses is `(entry.authz.ref, "meeting_host")`. Connectors trusts tilo-api's user id as it
     trusts its evidence. CON-D9 left "bind `user_id` to the signed-in principal" to an HTTP ticket, and tilo-api
     is that binding.
5. **Send, in tilo-connectors.**
   - **HB-03.** The draft is checked first: the SHA-256 of the decoded bytes equals `content_sha256`,
     `artifact_id` and `version` equal `entry.item`, and the document parses as kind `meeting_event`.
   - **HB-04.** The entry goes through connectors' own `Outbox`, built per request over a fresh in-memory store.
     `enqueue(entry, evidence)` runs the schema, OB-02 and OB-01/OB-05 (`tilo_policy.check_entry`), and
     `dispatch_due()` mints the `Grant`. The adapter's `execute_side_effect` runs only under that grant, so SEC-03
     holds in both services and the static scan does not change. Connectors keeps no outbox state between
     requests. Exactly-once delivery at Google rests on the event id being the outbox marker: a retry gets a 409
     and reads the earlier event (MH-13).
   - **HB-05.** The adapter's checks MH-10 to MH-14 apply unchanged, with `owner_of` answering
     `evidence.world_owner`, so MH-11 compares `world_owner`, `draft.owner` and `authz.ref` from the request.
   - **HB-06. The grant must predate the approval.** The token record gains `connected_at`. It is set when a
     connection is made from nothing or from `expired`, kept on refresh and re-consent, and sealed into the
     record's AAD, so no other Firestore writer can move it. A send whose `entry.authz.at` is earlier than
     `connected_at` is `refused`. A grant revoked and reconnected after the approval never sends it, whether or
     not tilo-api heard of the revoke.
   - The answer is `sent` with the receipt the adapter made (captured per request; connectors stores no
     artifact); `refused` for `SideEffectRefused` (nothing sent); `possibly_sent` for `PossiblySent` or an
     ambiguous earlier attempt; or `retry` with `may_have_sent`. That flag is false for not connected, expired,
     missing scope or a KMS outage, and true for a Google 5xx or a lost answer. Connectors drops its own
     `data.transfer` and `alert.raised` parts: tilo-api's outbox writes the world's one transfer and raises its
     own alert (one writer per world).
6. **tilo-api's stub.** `MeetingHostRpc` takes `MeetingHostAdapter`'s place in the host run's connector map. Its
   `execute_side_effect(entry, grant)` is called only by tilo-api's outbox. It reads the pinned draft from the
   run's store (hash-checked, AR-01), takes the evidence the run handed it for that outbox id before the enqueue,
   posts, validates the answer against the contract and maps it:

   | Connectors answers | The stub | tilo-api's outbox |
   | --- | --- | --- |
   | `sent`, and HB-07 holds | stores the receipt through the run's `_Receipts` (step 9 unchanged) and returns | `sent`, one `data.transfer` |
   | `refused`; 401, 403 or 422 (refused before anything acted); its own 503 `not_configured` | raises `SideEffectRefused` | `failed`, no alert |
   | `possibly_sent`, or `sent` with HB-07 broken | raises `PossiblySent` | `failed`, alert (FR-AGT-13) |
   | `retry` with `may_have_sent` false | raises a retryable error, not ambiguous | stays due |
   | `retry` with `may_have_sent` true; any other 5xx; a timeout; a lost answer | raises a retryable error, ambiguous | stays due, ambiguous; MH-13 stops a second invitation |

   **HB-07.** A `sent` answer is checked before anything is stored. `receipt.event_ref` equals
   `side_effect_marker(entry)`; its `world_id`, `outbox_id` and `draft` equal the entry's; its `meeting_id` and
   `owner` equal the draft's. The stub's HTTP timeout (20 s) stays under the outbox lease (30 s).
7. **Revoke and expiry reach the abandon sink.** Every call to connectors starts in tilo-api, so every broker
   event happens inside a call and its `parts` come back in that call's answer. tilo-api hands each part to
   `meeting_host.on_connection_event` under MTG-WIRE-1's `connection_sink` rule (a sink error never fails the
   call). The three cases:
   - **Disconnect in Tilo.** tilo-api first abandons the owner's unsent `meeting_host` entries (the same function,
     with a part built from the owner's own request), then calls `disconnect`, then handles the returned parts.
     The call is idempotent, so a lost answer is retried.
   - **Revoked at Google, or expired** (`invalid_grant` at refresh). Connectors finds out at the next token use,
     which is always inside a send (or a join-link), and the part rides that answer.
   - **Nothing heard** (a crash between the revoke and the answer). HB-06 still refuses the stale approval at
     connectors.

   `on_connection_event` treats `connection.expired` for `meeting_host` like `connection.revoked`, which amends
   BQ-MTG09-23: an expiry is Google refusing the grant, so an approval given under it must not fire after a new
   consent. `status` is a store read only (no token use, no Google call), so it emits nothing and has no `parts`.
8. **The live gate and failure modes (EFF-01).** Only tilo-connectors calls Google with a token, so only that
   service carries `LIVE=1`, and only the user sets it. In dev and CI, connectors' routes run on `FakeKms`,
   `InMemoryTokenStore` and `ReplayTransport`. tilo-api's tests use a fake client, or the connectors app in
   process with a fake verifier: no network and no paid call.

   | Condition | Result |
   | --- | --- |
   | tilo-api has no `TILO_CONNECTORS_URL`, or cannot mint an ID token (a laptop) | `get_meeting_host_client` is 503 `not_configured`; `POST /v1/meetings/{id}/host` answers it before any run starts |
   | Connectors lacks `TILO_TOKEN_STORE=firestore` and a valid `TILO_FIRESTORE_PROJECT`, `TILO_KMS_KEY`, the OAuth settings, `LIVE=1` or the HB-01 variables | every meeting-host route answers 503 `not_configured`; the host route's preflight `status` turns that into its own 503, so no gate card is raised that could never send |
   | A seam build failed | 503 for 30 s, then the next request tries again; never cached for good, so a fixed setting needs no restart |
   | A not-connected owner at host time | unchanged by this ADR (the send fails after the gate with a plain reason); BQ-ADR32-1 |

   A response or log names a fixed code or the setting's name, never a value or an exception's text.
9. **Infra (ticket T5; the user applies it).**
   - `connectors.invoked_by` becomes `["harness", "api"]`, and `cloud_run.tftest.hcl` expects exactly those two on
     connectors (browser and render stay harness-only).
   - `connectors.max_instance_count` becomes 1 until the CAS ticket (T7) lands. This is CON-D9's own default,
     "single `tilo-connectors` instance until the Firestore-backed stores land"; the plan has 2 today.
   - ACCESS.md section 2 (connectors row) and decision 8.1 ("Only the harness invokes connectors") are updated.
   - tilo-api gains no KMS, Secret Manager or Firestore role. `security_iam.tftest.hcl` does not change and is the
     acceptance check: one decrypter, and the client secret for connectors only. tilo-api already reaches
     internal services through its VPC egress.
   - Environment: tilo-api `TILO_CONNECTORS_URL`; connectors `TILO_CONNECTORS_AUDIENCE`, `TILO_MEETING_HOST_CALLER`,
     plus the store, KMS, OAuth and `LIVE` settings MTG-WIRE-1 read in tilo-api (they move with the code).
10. **MTG-WIRE-1 (0bde0544) is not merged as it is.**

    | Piece | Fate |
    | --- | --- |
    | `deps._host_seam` (built once per process; a failed build answers 503 and is not remembered) | kept, for the one new seam `get_meeting_host_client`, with the 30 s negative cache |
    | `deps.get_token_broker`, `deps.get_meeting_host_transport`, `HostSeams.broker`/`.transport` | dropped; `HostSeams` gets `host_client` |
    | `host_wiring.FirestoreTokenStore` | moved to `services/connectors`, with follow-ups 1 and 4 below |
    | `open_host_broker` (env gates: store, project regex, KMS key regex, `LIVE`, OAuth settings), `_default_kms`, `open_host_transport` | moved to connectors' composition root |
    | `connection_sink` | its rule stays, applied by tilo-api's client to the returned `parts` |
    | `HostRun` building `MeetingHostAdapter` in tilo-api | replaced by `MeetingHostRpc`; `_Drafts` and `_Receipts` stay in tilo-api |
    | `services/api/tests/test_MTG_WIRE_1_host_wiring.py` | the env-gate and store tests move with the code to `services/connectors/tests`; the sink test becomes a client test |
    | `services/api/src/tilo_api/host_wiring.py` | deleted |

## Follow-ups the security review raised (built in the tickets below)
1. **`{user}__{connector}` key ambiguity.** `user_id` (`^u_[0-9A-Za-z_]{1,48}$`) and `connector_id`
   (`^[a-z][a-z0-9_]{1,31}$`) may both contain `__`, so `u_a__b` with `c` and `u_a` with `b__c` share the document
   `u_a__b__c`. The AAD binds kind, user and connector, so a collision can overwrite or delete a grant but never
   decrypt one. Fix (T2): two document ids and no separator, `token_grants/{user_id}/connectors/{connector_id}`,
   each fullmatched against its `common.schema.json` pattern before a path is built; `connectors_of` lists the
   subcollection.
2. **No backoff on failed builds.** `_host_seam` retries a failed build on every request, so a misconfigured
   service rebuilds clients on every call. Fix (T2, T4): a 30 s negative cache per seam (decision 8).
3. **Revoke events from outside the process.** Decision 7 and HB-06.
4. **In-memory retry store.** The broker's failed-revoke retry store defaults to memory, and connectors scales to
   zero, so a pending revoke is lost on the next cold start and the bot grant stays live at Google. Fix (T2): a
   Firestore retry store, `token_revoke_retry/{user_id}/pending/{key}`, sealed like every record. The alert is
   still raised at the failure.
5. **No CAS (CON-D9).** The broker's locks are per process, and the plan allows two connectors instances, so a
   refresh can rewrite a record that a disconnect on the other instance just deleted. Fix (T7): Firestore
   preconditions on token-store writes (create-only for a new record; update and delete on the `update_time`
   read), with the broker re-reading on a conflict. Until it lands, connectors runs one instance (decision 9),
   which T5 sets.

## Alternatives considered
1. **A user-accepted SEC-02 exception for the bot grant only.** Rejected. PRD 16.1 lists hard rules. KMS IAM is
   per key and `oauth-tokens` seals every person's grant, so the exception would need a second key and a second
   KMS setup in the broker. It would still put a live OAuth token in the internet-facing service (`allUsers`).
   Two brokers over one store with per-process locks race (CON-D9) and split CON-D10's grant-group logic, and three
   pinned tests would have to be weakened.
2. **Widen IAM** (decrypt on `oauth-tokens` and the client secret for tilo-api). Rejected: the public service
   could then read every person's Gmail, Drive and Calendar tokens.
3. **Relay through harness**, which keeps PRD 6.1's only drawn edge into connectors. Rejected: the run lives in
   tilo-api, a pass-through route adds a hop and a second caller check, and connectors would see harness as the
   caller, hiding the real one.
4. **Hand connectors' short-lived access token to tilo-api per send.** Rejected: a plaintext token leaves
   connectors (SEC-02's intent; PRD 16.1 rule 4).
5. **An asynchronous queue (Cloud Tasks or Pub/Sub) to connectors.** Rejected for the send, because the run waits
   for the receipt (step 9), and not needed for revoke events (decision 7).
6. **A Firestore outbox both services read**, with connectors fetching the entry and evidence by reference instead
   of trusting copies. Stronger, but it waits for ADR-0026's durable store and a Firestore outbox store; it is kept
   as the hardening path below.

## Consequences
- SEC-02 holds: the FR-CON-02 import test passes, and `security_iam.tftest.hcl` is unchanged.
- tilo-connectors gets its first real routes: internal, scale to zero, no paid call added. One extra internal hop
  per send, well under a second against a T3 gate's human wait.
- One new contract (`meeting_host_rpc`, additive, 1.0.0).
- **Residual trust.** Connectors trusts tilo-api's evidence, world owner and user id, because tilo-api is the
  authorisation service and holds the events. A compromised tilo-api could ask for invitations that pass every
  MH, OB and HB rule for an owner who connected `meeting_host`. It could not read, keep or replay a token, or call
  any other Google API. Hardening once ADR-0026's Firestore event store is live: connectors reads `reserved_by`
  and `authorised_by` itself by `(world_id, seq)` (it already holds `datastore.user`) and ignores the copies.
- `datastore.user` is project-wide on api, harness, render and connectors, so any of them can overwrite or delete
  a sealed token record, but none can read one. The AAD (kind, user, connector, scopes, expiry, `connected_at`)
  makes a moved or edited record fail to decrypt.
- PRD 6.1's diagram draws only harness to connectors. This adds tilo-api to connectors for the meeting-host routes
  only, and ACCESS.md 8.1 and `cloud_run.tftest.hcl` change with it, as part of what the user approves.
- Channels' mail reader fits the same pattern, but channels has no path to connectors (no VPC egress, no
  invoker). That is its own decision (BQ-ADR32-1).

## Tickets (small, in this order)
- **T0.** The user approves this ADR, including the infra test change in decision 9.
- **T1 (architect).** `contracts/meeting_host_rpc.schema.json` 1.0.0: request and answer for send, status and
  disconnect, closed, with caps (body at most 64 KiB, recipients at most `MAX_RECIPIENTS`), valid and invalid
  fixtures and codegen. Additive.
- **T2 (reach-builder, connectors only).** `FirestoreTokenStore` with nested paths, the Firestore retry store,
  `connected_at` sealed, and `open_broker(env)` with MTG-WIRE-1's env gates and the 30 s negative cache. Tests
  move from `test_MTG_WIRE_1_host_wiring.py`. Security review.
- **T3 (reach-builder, connectors).** The three routes: HB-01 (OIDC caller check), HB-03 to HB-06, the per-request
  `Outbox`, part capture. Opus security review.
- **T4 (reach-builder, api).** `MeetingHostRpc` and HB-07; `deps.get_meeting_host_client`; the host route's
  preflight `status`; `on_connection_event` takes `connection.expired`; delete `host_wiring.py` and the two seams.
  The test-writer extends the FR-CON-02 import test to `tilo_connectors.live` and `tilo_connectors.adapters` for
  `services/` outside connectors. Security review.
- **T5 (reach-builder, infra).** Invoker, `cloud_run.tftest.hcl`, connectors at most one instance, ACCESS.md. The
  user applies it.
- **T6 (reach-builder, api).** The owner's connection routes: status, and disconnect with abandon-first. The
  test-writer pins their paths and codes.
- **T7 (reach-builder, connectors).** CAS on token-store writes (CON-D9); connectors may then go back to two
  instances.
- **Then the user:** the environment values, the apply, `LIVE=1` on connectors only, and the first live invitation
  to `tilotesting@gmail.com` after the user's go (ADR-0024 accepted amendment 5).
- **Not in this list** (BQ-ADR32-1): connecting the bot account on a deployed stack (the consent code exchange),
  and amendment 4's join-link route, which follows T3's pattern in its own ticket.
