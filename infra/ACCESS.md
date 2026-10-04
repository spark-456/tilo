# Tilo access matrix (P0-07b audit)

One place that says which identity may touch which Google resource, why, and
what was left out on purpose. Derived from PRD 6.1-6.5, 11-13, 16.1 and from
the code (`services/*/src`, `packages/providers`, `config/*.yaml`). Terraform
is the source of truth for what exists; `infra/envs/dev/tests/*.tftest.hcl`
assert the rules that matter.

Status values: **present** (applied earlier), **added** (this pass),
**console** (the user does it once, Terraform cannot), **deferred** (reason
given).

## 1. APIs (all in `local.required_apis`, `infra/envs/dev/main.tf`)

| Group | APIs | Status |
| --- | --- | --- |
| Runtime and data | run, artifactregistry, firestore, pubsub, bigquery, storage, cloudkms, secretmanager, cloudtasks, compute | present |
| Identity and CI | iam, iamcredentials, sts, cloudresourcemanager, cloudbilling, billingbudgets, cloudbuild | present |
| Models and Firebase | aiplatform (Gemini, Sessions, Memory Bank, code execution, Gen AI evaluation, Gemini audio), firebase, firebasehosting | present |
| PRD 6.3 services | modelarmor, cloudscheduler, identitytoolkit, firebaseappcheck, monitoring, cloudtrace, logging | added (P0-07b, first part) |
| Workspace connectors | gmail, calendar-json, drive | added (adopts the hand-enabled APIs) |
| Audit pass | serviceusage, firebaserules (Firestore rules deploy), recaptchaenterprise (App Check provider), docs, sheets, slides (Google output, FR-CON-11), bigquerystorage (Pub/Sub to BigQuery) | added |
| Left out | speech, texttospeech (no `SpeechProvider` profile exists in `config/`; Gemini audio rides on aiplatform), any image or video API (render makes charts by code, PRD 12.4) | deferred: add the API and a test the day a Google STT/TTS profile is configured |

## 2. Per service

Roles are per resource unless marked **project**; a project-level role is
listed only where Google offers no narrower scope.

| Service | Calls | IAM granted | Secrets (accessor) | Status |
| --- | --- | --- | --- | --- |
| `tilo-api` | Firestore; Cloud Tasks enqueue; Vertex AI (Router: approaches, Director); Model Armor (intake screen); `artifacts` bucket (uploads FR-INT-02, downloads PRD 6.2); Firebase ID-token and App Check verification (public keys, no IAM) | project: `datastore.user`, `cloudtasks.enqueuer`, `aiplatform.user` (added), `modelarmor.user` (added). Bucket `artifacts`: `objectCreator`, `objectViewer` (added). `serviceAccountUser` on `tilo-tasks-invoker` | `email-action-link-signing-key` | mixed, see cells |
| `tilo-harness` | Firestore; Cloud Tasks; Vertex AI; Model Armor (model output, tool output); Pub/Sub publish on `tilo-events`; buckets `archive`, `artifacts`, `snapshots`; connectors, browser, render | project: `datastore.user`, `cloudtasks.enqueuer`, `aiplatform.user`, `modelarmor.user` (added). Topic `tilo-events`: `pubsub.publisher`. `archive`: `objectCreator` (present), `objectViewer` (added). `artifacts` and `snapshots`: `objectCreator`, `objectViewer` (added). `run.invoker` on connectors, browser, render | none | mixed |
| `tilo-channels` | Vertex AI (triage, drafting); Model Armor (inbound mail and WhatsApp text); `tilo-api`; Gmail push, renew and poll endpoints | project: `aiplatform.user`, `modelarmor.user` (added). Holds no Firestore, Pub/Sub or Storage role (writes through the API, SEC-12) | `whatsapp-api-token`, `channels-webhook-signing-key` (present); `whatsapp-webhook-verify-token`, `channel-binding-hmac-key`, `channel-number-encryption-key`, `webpush-vapid-private-key` (added) | mixed |
| `tilo-connectors` | Firestore (token store, outbox); Cloud KMS; Google Workspace APIs with the user's OAuth token (Gmail, Drive, Calendar, Docs, Sheets, Slides) | project: `datastore.user`. Key `oauth-tokens`: `cryptoKeyEncrypterDecrypter` (added: replaces `cryptoKeyDecrypter`, because `tokens.py` wraps a fresh data key per record). `run.invoker` for harness | `workspace-oauth-client` | mixed |
| `tilo-browser` | Allowlist egress proxy only; model calls for computer use are made by the harness | none (SEC-12: no Firestore, Datastore or Storage) | none | present |
| `tilo-render` | Firestore; `artifacts` bucket; Slides and Docs go through connectors | project: `datastore.user`. Bucket `artifacts`: `objectAdmin` (only service that may overwrite) | none | present |
| `tilo-sandbox-web` | nothing | none | none | present |

Other identities:

| Identity | Grants | Status |
| --- | --- | --- |
| `tilo-tasks-invoker` (Cloud Tasks OIDC) | `run.invoker` on harness | present |
| `tilo-gmail-push` (Pub/Sub push OIDC) | `run.invoker` on channels; Pub/Sub service agent holds `serviceAccountTokenCreator` on it | added |
| `tilo-gmail-scheduler` (Scheduler OIDC) | `run.invoker` on channels | added |
| `gmail-api-push@system.gserviceaccount.com` | `pubsub.publisher` on topic `tilo-gmail-notifications` only | added |
| Pub/Sub service agent | custom insert-only role on dataset `tilo_ledger` | present |
| Cloud Storage service agent | `cryptoKeyEncrypterDecrypter` on key `archive` | present |
| `tilo-deployer` (WIF, `refs/heads/main` only) | `run.developer` per service; `serviceAccountUser` per runtime SA; Artifact Registry writer on repo `tilo`; (added) `serviceAccountUser` on `tilo-cloudbuild`, `objectAdmin` on the build staging bucket. No project role | present and added |
| `tilo-cloudbuild` (build identity) | Artifact Registry writer on repo `tilo`; `objectViewer` on the staging bucket; project `logging.logWriter` | added |

## 3. Pub/Sub, Scheduler, Cloud Tasks

| Resource | Purpose | Status |
| --- | --- | --- |
| Topic `tilo-events` and subscription `tilo-events-to-bigquery` | Ledger (PRD 13.2) | present |
| Topic `tilo-gmail-notifications` | Gmail `users.watch` target (FR-CHN-08) | added |
| Subscription `tilo-gmail-push` | Push to `tilo-channels` `POST /internal/gmail/push`, OIDC as `tilo-gmail-push`, audience = channels URL, no inactivity expiry | added |
| Scheduler `tilo-gmail-renew` (daily 03:00 UTC) | `POST /internal/gmail/renew` on channels (re-watch) | added |
| Scheduler `tilo-gmail-poll` (every 5 min) | `POST /internal/gmail/poll` on channels (polling fallback) | added |
| Cloud Tasks queue `runs` | api to harness | present |
| Scheduler jobs for the sweeper and user schedules | PRD 6.3 | deferred: no sweeper endpoint exists; add with that ticket |

Dependency: the three `/internal/gmail/*` paths do not exist in
`services/channels` yet (`GmailPushEndpoint` and `MailWatcher` exist, but no
HTTP routes). The service must verify the OIDC token itself (it does, in
`GmailPushEndpoint.receive`); the audience is the channels service URL and the
expected email is `tilo-gmail-push@<project>.iam.gserviceaccount.com`. Renew and
poll must check the caller is `tilo-gmail-scheduler@<project>...`.

## 4. Storage ownership (PRD 13.2, FR-INT-02)

| Bucket | Writes | Reads | Note |
| --- | --- | --- | --- |
| `artifacts` (versioned, 365 d) | render (`objectAdmin`), api and harness (`objectCreator`) | api, harness (`objectViewer`) | Uploads become new objects, never overwrites |
| `archive` (CMEK, 30 d) | harness (`objectCreator` only) | harness (`objectViewer`, chain check) | Nobody can overwrite or delete |
| `snapshots` (90 d) | harness (`objectCreator`) | harness (`objectViewer`) | |
| `<project>-build-staging` (7 d) | deployer | `tilo-cloudbuild` | Source upload for `gcloud builds submit` |

## 5. Secret Manager slots (names only; values added by the user)

Existing: `workspace-oauth-client`, `whatsapp-api-token`,
`channels-webhook-signing-key`, `email-action-link-signing-key`. Added:
`whatsapp-webhook-verify-token`, `channel-binding-hmac-key`,
`channel-number-encryption-key`, `webpush-vapid-private-key`. No version is
ever created by Terraform (PRD 16.1 rule 4).

## 6. OAuth consent screen: scopes to add once

| Scope | Why | Class |
| --- | --- | --- |
| `openid`, `email`, `profile` | Google sign-in (Firebase Auth) | basic |
| `https://www.googleapis.com/auth/gmail.readonly` | read, search, history (FR-CON-04, FR-CHN-08) | restricted |
| `https://www.googleapis.com/auth/gmail.compose` | drafts | restricted |
| `https://www.googleapis.com/auth/gmail.send` | threaded send | restricted |
| `https://www.googleapis.com/auth/drive.file` | picked files and files Tilo creates, incl. Slides, Docs and Sheets output (the Docs, Sheets and Slides APIs accept it for files the app created) | non-sensitive |
| `https://www.googleapis.com/auth/calendar.readonly` | availability (FR-CON-14) | sensitive |
| `https://www.googleapis.com/auth/calendar.events` | event writes | sensitive |

Never requested: `mail.google.com`, `gmail.modify`, full `drive`.

## 7. Console steps for the user (Terraform cannot do these)

1. OAuth consent screen: add the scopes above, add test users (up to 100), set
   the app to Testing. Create the web OAuth client; set its redirect URI to the
   connectors callback (`GOOGLE_OAUTH_REDIRECT_BASE_URL`).
2. Put values in the eight secrets (`gcloud secrets versions add`).
3. Identity Platform: enable Google sign-in and anonymous sign-in; add the
   hosting domain to authorised domains.
4. App Check: register the web app with a reCAPTCHA Enterprise key, then switch
   enforcement on for Firestore and Storage after the client sends tokens.
5. Firestore security rules: `firebase deploy --only firestore:rules` (needs the
   deployer decision in section 8, or run it yourself).
6. Vertex AI quotas: raise per-minute quotas for the Gemini models in use
   (IAM and Admin, Quotas); Terraform has no resource for them.
7. Model Armor: check `var.model_armor_location` is a supported region the first
   time apply runs; set the template id `tilo-default` in the safety provider
   config.
8. Meta WhatsApp Business: webhook URL, verify token and app secret (stored in
   the secrets above).
9. First Gmail watch: after the endpoints exist, each user's connect flow calls
   `users.watch` with topic `projects/<project>/topics/tilo-gmail-notifications`.

## 8. Open decisions (need the user or a contract change)

1. **channels needs connectors.** `GmailPushEndpoint`, `MailWatcher` and the
   autopilot send path call Gmail through "an RPC client to tilo-connectors",
   but the tests (PRD 6.1) say connectors is invokable by harness only, and
   channels has no VPC egress to reach an internal-only service. Either route
   channels to connectors through the harness, or change the test (invoker
   `channels` on connectors plus Direct VPC egress for channels). Not changed here.
2. **email-action-link-signing-key accessor.** The secret is readable by api
   only, but `links.py` (sign and verify) lives in `tilo-channels`. If channels
   signs the links, it needs the accessor. Not changed here: an existing test
   pins the exact set.
3. **Deployer project roles.** CI that uses Cloud Build or deploys Firebase
   needs project roles (`cloudbuild.builds.editor`, `firebasehosting.admin`,
   `firebaserules.admin`; none can be scoped to a resource). The SEC-12 test
   says the deployer holds none. Default is none; set
   `deployer_project_roles` to opt in, or build with Docker on the runner and
   push to Artifact Registry (already allowed) and deploy Firebase by hand.

## 9. Intentionally not granted

- Any project-wide `run.admin`, `storage.*`, `secretmanager.*`, `cloudkms.*`,
  `pubsub.publisher`, or `iam.serviceAccountUser`.
- `tilo-browser`: any data, model or secret access.
- `tilo-channels`: Firestore, Pub/Sub publish, Storage.
- `tilo-api`: decrypt on `oauth-tokens`, any access to `archive`, publish on `tilo-events`.
- Anyone but `tilo-connectors`: the `oauth-tokens` key.
- `modelarmor.user` for connectors and browser (the harness screens tool output
  after it returns).
- Service account keys (none exist) and secret versions in code.

## 10. Assumptions (the PRD does not decide these)

1. Harness, not browser, makes computer-use model calls; browser has no `aiplatform.user`.
2. Vertex Sessions, Memory Bank, code execution and Gen AI evaluation are covered by `aiplatform.user` on harness.
3. api and harness store uploads and intermediate artifacts (create and read); only render overwrites.
4. Harness may read `archive` to verify the hash chain; api cannot read it, so the Trace link to a raw record is served by harness (not yet decided in the PRD).
5. Masked screenshots reach Storage through harness, because browser holds no Storage role.
6. Channels binds numbers with an HMAC key and a cipher key held in Secret Manager (the `binding.py` design); the web-push VAPID key is a secret.
7. The Gmail endpoints live on `tilo-channels` (where `GmailPushEndpoint` is), at `/internal/gmail/{push,renew,poll}`.
8. `roles/modelarmor.user` and `roles/aiplatform.user` are project-level: neither product offers narrower IAM.
9. The WhatsApp `channels-webhook-signing-key` slot holds the Meta app secret used by `verify_signature`.
