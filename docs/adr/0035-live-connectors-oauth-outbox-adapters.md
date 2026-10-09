# ADR-0035: Live Google connectors: OAuth connect through tilo-api, a durable Firestore outbox, real adapters in tilo-connectors

- Status: Proposed (9 Oct 2026). The supervisor accepts it under the user's delegation; the user applies decision 9.
  The merger may renumber.
- Deciders: user (standing order, 9 Oct 2026: every feature fully live by 17 Oct, no fixture-only features; the live
  switch), supervisor (acceptance), architect
- Requirement: FR-CON-02, FR-CON-03, FR-CAL-04, FR-AGT-13; SEC-02, SEC-03; EFF-01; PRD 6.5, 11.5, 12.1, 16.1 rule 2;
  CON-D9, CON-D10; ADR-0024, ADR-0026, ADR-0032 (HB-01 to HB-07), ADR-0032a (HB-08, HB-09)
- Questions: closes BQ-ADR32-1 item (1). New BQ-ADR35-1 to BQ-ADR35-4. New rule ids LC-01 to LC-14 (unused prefix).

## Context
1. `tilo_connectors.consent.ConsentService` already runs Google's code flow with PKCE (S256), `include_granted_scopes`
   and a single-use 600 s state bound to `(user_id, connector)`, in memory, but no route serves it. The broker
   (`tokens.py`) stores, refreshes and revokes sealed grants; `gmail`, `google_drive` and `google_calendar` share one
   person grant (CON-D10, `grant_group`). `OAuthSettings.redirect_uri` is `<GOOGLE_OAUTH_REDIRECT_BASE_URL>/oauth/google/callback`.
2. `GmailAdapter` drafts and sends, `DriveAdapter` saves, `CalendarAdapter` only reads (`config/connectors.yaml`: calendar
   writing "is not declared until it is built"). `real.py`/`real_writes.py` are a laptop tool behind a typed `yes`.
3. In tilo-api, `deps.get_connector_adapters()` returns `{}` and `deps.get_outbox_store()` is a per-process
   `InMemoryOutboxStore`, so an approved card sends nothing and a second instance or a restart loses the outbox.
4. tilo-api signs people in with a Firebase ID token in the `Authorization` header (`_verified_principal`); a browser
   redirect from Google carries no such header. ADR-0032 forbids tokens, the KMS key and the client secret outside
   tilo-connectors; its RPC (HB-01, POST, ids in the body) is the one path from tilo-api to connectors.

## Decision
1. **Contract.** Extend `contracts/meeting_host_rpc.schema.json` additively (minor), not a new file: it is the one
   tilo-api to connectors boundary, already holds `user_request`, `parts`, the error codes and 0032a's `/internal/connections/views`, so a second file would duplicate them under the same caller check.
2. **Routes.** All connectors routes take HB-01 (OIDC caller = tilo-api's account), the 64 KiB cap and a closed schema.
   tilo-api sends only the principal's own `user_id` (HB-02). No answer carries a token, verifier, secret or mail text.

   | tilo-api (public, signed in) | tilo-connectors (internal) | Answer |
   | --- | --- | --- |
   | `POST /v1/connectors/connect` `{connector, capabilities}` | `/internal/connections/start` `{user_id, connector, capabilities}` | `{authorize_url}`, or `{authorize_url: null}` when nothing is missing |
   | `POST /v1/connectors/callback` `{state, code?, error?}` | `/internal/connections/callback` `{user_id, state, code?, error?}` | `{connector, scope_lines, parts}` |
   | `POST /v1/connectors/disconnect` `{connector}` | `/internal/connections/disconnect` `{user_id, connector}` | `{revoked_at_provider, parts}` |
   | (the run's outbox, decision 5) | `/internal/side-effects/execute` `{entry, evidence, items}` | `{outcome, result?, may_have_sent?, parts}` |

   `GET /v1/connectors` (0032a views) is the scope read. `meeting_host` uses the same three connection routes, so the
   bot account connects on a deployed stack (closes BQ-ADR32-1 (1)); MH-C1 stays. tilo-api hands `parts` to its
   connection sink and event writer as ADR-0032 decision 7 does (one writer per world); no new event type.
3. **Consent redirect on a deployed stack.**
   - **LC-01.** Google redirects the browser to the web app, `https://<tilo-dev web origin>/oauth/google/callback`
     (`GOOGLE_OAUTH_REDIRECT_BASE_URL` = the web origin; Firebase Hosting serves the SPA there). Not tilo-api: a
     redirect carries no ID token.
   - **LC-02.** Before opening `authorize_url` the web saves its `state` in `sessionStorage`. The callback page first
     replaces its URL (`history.replaceState`, so `code` leaves the address bar and history), then posts only when the
     returned `state` equals the saved one, with the person's ID token, and clears the saved value.
   - **LC-03. What crosses tilo-api.** The authorize URL (client id, scopes, challenge, state; no secret) and the
     one-time code. The code is useless without the PKCE verifier and the client secret, which never leave
     connectors, and it is spent on first use. tilo-api never logs, stores or echoes `code` or `state`.
   - **LC-04.** The callback path is served with `Referrer-Policy: no-referrer` and `Cache-Control: no-store`, and
     loads no third-party asset.
   - **LC-05. CSRF and account binding.** Connectors pops the state (single use, 600 s) and refuses unless the flow's
     `user_id` equals the caller's principal (`handle_callback` today). Another person's code or state never binds a
     Google account to this person. Every refusal is one fixed text ("start again").
4. **Incremental scopes (LC-06).** `start` asks only for the declared scopes of the named capabilities minus those
   already granted (`scopes_needed`), with `include_granted_scopes=true`, so the one person grant grows per
   capability (CON-D10). When a planned action needs a capability whose scope is missing (registry minus 0032a views,
   computed in tilo-api), the run raises a `consent` card; only the person's Connect starts a flow (CR-13). A partial
   grant connects only what was granted; a later action asks again. Disconnecting any person connector revokes the
   shared grant at Google, so all three show `available`; the web says so before the person confirms.
5. **Real adapters run only in connectors (LC-07).** `/internal/side-effects/execute` generalises ADR-0032's
   `/meeting-host/send` to `gmail`, `google_drive` and `google_calendar`: `items` (the entry's `item` and each
   attachment as `{artifact_id, version, content_sha256, content_b64}`) are hash-checked first (HB-03); the entry goes
   through a per-request `Outbox` whose `dispatch_due()` mints the `Grant` (HB-04, SEC-03); HB-06 refuses a grant
   newer than the approval; `owner_of` answers `evidence.world_owner`. The answer is HB's four outcomes with
   `result = {resource_id, marker}` only. `meeting_host` keeps its own route.
   - **LC-08.** `get_connector_adapters()` returns one `ConnectorRpc` stub per live connector (HB decision 6's
     outcome mapping); a `sent` answer is stored only when `result.marker == side_effect_marker(entry)`. A demo
     session's map stays `{}`. `real.py`/`real_writes.py` stay a laptop tool and are not on this path: the approval
     recorded in tilo-api's events is the human act.
6. **Tiers (data, `config/autonomy.yaml`; the policy engine decides, never a model; T3 always a person).**

   | Action | Tier | Note |
   | --- | --- | --- |
   | `read_email`, `search_email`, `read_file`, `list_files`, `read_events` | T1 | no gate, no outbox entry |
   | `create_draft`, `save_file`, `save_as_google_file` | T1 | approval card, undo window |
   | `send_email` | T2 | `new_recipients` or `attachments` raise it to T3 |
   | `create_event` (new; `google_calendar` `write`, scope `calendar.events.owned`) | T1 | own primary calendar, no guests |
   | `create_event_with_guests` (new; capability `send`, same scope) | T3 | Google emails the guests (FR-CAL-04) |

   - **LC-09.** `create_event` with any attendee is refused by the adapter before any call (FR-CAL-04 property).
   - **LC-10. Draft before send.** tilo-api enqueues a `send_email` only when the same world holds a `sent`
     `create_draft` entry for the same item (artifact id, version, content hash): the draft is in the person's Gmail and
     on the card before the send is approved. The send carries that pinned content (`messages.send`), never the Gmail
     draft as it may since have been edited. Otherwise the enqueue is refused with a fixed reason.
7. **Durable outbox in tilo-api (LC-11 to LC-13).**
   - **LC-11.** `FirestoreOutboxStore` (in `services/api`) implements `InMemoryOutboxStore`'s methods, mutators
     included, in tilo-api's Firestore database (ADR-0026). One document per entry, `outbox/{outbox_id}`, holds the
     entry, the send lease `{holder, until}`, the retry state, the pending transfer, the pending alert and `alerted`,
     so every mutator is one transaction on one document and PI-17's same-write rule holds. The idempotency key is a
     create-only `outbox_keys/{world_id}/keys/{sha256(key)}` written in the insert's transaction; a revoke writes it
     with `revoked: true` and it is never pruned. Ids are fullmatched against `common.schema.json` before any path.
   - **LC-12.** Two instances are safe: a claim is a transaction on the lease (30 s, the store's clock, PI-12 skew
     unchanged). An attempt whose lease expired is ambiguous; the adapters' provider markers (Gmail `Message-ID`, Drive
     `appProperties`, Calendar event id) make the next attempt find it (OB-03). The run thread dispatches after
     enqueue as today, and the existing tilo-api schedule tick also calls `dispatch_due()`, so a dead instance's due
     entry goes out within one tick.
   - **LC-13.** Selected by `TILO_OUTBOX_STORE=firestore` with ADR-0026's project gate, else in memory. `Outbox`, the OB
     rules, `tilo_policy.check_entry`, SEC-03 and `outbox.schema.json` do not change. Demo sessions keep their own
     in-memory outbox.
8. **Live gate (LC-14, EFF-01).** Only tilo-connectors calls Google, so only it carries `LIVE=1`, set by the user. Dev
   and CI: connectors on `FakeKms`, `InMemoryTokenStore`, `ReplayTransport`; tilo-api with a fake client or the
   connectors app in process with a fake verifier; the outbox store suite on the Firestore emulator. No paid call.
9. **Infra (the user applies).** Connectors: `GOOGLE_OAUTH_REDIRECT_BASE_URL` = the web origin; still one instance
   (consent flows are in memory until ADR-0032 T7 adds CAS, with a Firestore flow store). tilo-api: `TILO_OUTBOX_STORE=firestore`.
   One Firestore composite index on `outbox` (`transfer_pending`, `enqueued_at`). Hosting headers for LC-04. No new IAM
   role: `security_iam.tftest.hcl` is unchanged.

## Failure modes
| Condition | Result |
| --- | --- |
| State unknown, spent, expired, another person's, or the connectors instance restarted mid-flow | 400, "start again"; nothing stored |
| Person denies, or grants none of the asked scopes | "consent was not granted"; a partial grant connects only what was granted |
| Code exchange fails, or KMS fails at store | nothing kept, the token discarded (revoked if no live grant shares it); "start again" |
| `LIVE` or an OAuth/KMS/HB setting missing on connectors | every route 503 `not_configured`; no card is raised that could never send |
| Revoked at Google, or the 7-day testing-mode expiry (PRD 11.5) | `expired` at the next token use; parts abandon unsent entries; views ask to connect again |
| tilo-api instance dies mid-send | lease expires; another instance or the tick re-claims; the marker lookup stops a duplicate |
| Firestore unavailable at enqueue | 503, no entry, nothing sent; the run reports the step failed with a plain reason |

## What the user configures
- The OAuth client (type Web application) in the tilo-dev project: authorised redirect URI exactly
  `https://<tilo-dev web origin>/oauth/google/callback`. No JavaScript origin is needed (the exchange is server side).
- Consent screen scopes: `gmail.readonly`, `gmail.compose`, `gmail.send`, `drive.file`, `calendar.readonly`,
  `calendar.events.owned`. Testing mode, test users `tilotesting@gmail.com` and the meeting bot account.
- Secrets: `workspace-oauth-client` (client id and secret) exists for connectors only; set
  `GOOGLE_OAUTH_REDIRECT_BASE_URL`; after the apply and the go, `LIVE=1` on tilo-connectors only.

## Consequences
- Every Google side effect is live through one reviewed path; SEC-02 and SEC-03 hold unchanged.
- tilo-api sees a one-time code per connect; residual trust is ADR-0032's (tilo-api's evidence and user id).
- One contract minor, two config actions, one Firestore index; connectors stays at one instance until ADR-0032 T7.

## Tickets (in order)
- **L1 (architect, S, no Opus).** Contract minor for decision 2's four routes, fixtures, codegen; `google_calendar`
  `write`/`send` with `calendar.events.owned` and the two actions in `connectors.yaml` and `autonomy.yaml`.
- **L2 (reach-builder, api, M, Opus).** `FirestoreOutboxStore`, the store suite run against memory and the emulator,
  the tick's `dispatch_due()`, the env gate (LC-11 to LC-13).
- **L3 (reach-builder, connectors, M, Opus).** `start`, `callback`, `disconnect` over `ConsentService` and the broker
  (HB-01, LC-05, LC-06), parts.
- **L4 (reach-builder, api + web, M, Opus).** The three public routes and seam; the web callback page and Connect
  buttons (LC-01 to LC-04); Hosting headers.
- **L5 (reach-builder, connectors, M, Opus).** `/internal/side-effects/execute`; `CalendarAdapter.create_event` (LC-09).
- **L6 (reach-builder, api, M, Opus).** `ConnectorRpc` stubs in `get_connector_adapters`, the marker check, LC-10.
- **L7 (reach-builder, infra, S, Sonnet security).** Env values, the index, ACCESS.md. The user applies it.
- **L8 (user, then supervisor).** Configure the client; the go; `LIVE=1` on connectors. Acceptance with
  `tilotesting@gmail.com`: connect Gmail read, then Drive write and Calendar write incrementally (one grant); a draft
  appears in Gmail; a send to the same address arrives once; a file lands in the Tilo folder; an event without guests
  appears and one cancelled in the undo window does not; disconnect leaves no Tilo access in the Google account and
  every view `available`.
