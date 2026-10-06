# Tilo access matrix (P0-07b audit)

One place that says which identity may touch which Google resource, why, and
what was left out on purpose. Derived from PRD 6.1-6.5, 11-13, 16.1 and from
the code (`services/*/src`, `packages/providers`, `config/*.yaml`). Terraform
is the source of truth for what exists; `infra/envs/dev/tests/*.tftest.hcl`
assert the rules that matter.

Rules are asserted in `infra/envs/dev/tests/access.tftest.hcl` (this audit)
and the P0-07 files beside it.

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
| `tilo-api` | Firestore; Cloud Tasks enqueue; Vertex AI (Router: approaches, Director); Model Armor (intake screen); `artifacts` bucket (uploads FR-INT-02, downloads PRD 6.2); Firebase ID-token and App Check verification (public keys, no IAM) | project: `datastore.user`, `cloudtasks.enqueuer`, custom role `tiloVertexGenerate` (`aiplatform.endpoints.predict` only) and `modelarmor.user` (added). Bucket `artifacts`: `objectCreator`, `objectViewer` (added). `serviceAccountUser` on `tilo-tasks-invoker` | none | mixed, see cells |
| `tilo-harness` | Firestore; Cloud Tasks; Vertex AI; Model Armor (model output, tool output); Pub/Sub publish on `tilo-events`; buckets `archive`, `artifacts`, `snapshots`; connectors, browser, render | project: `datastore.user`, `cloudtasks.enqueuer`, `aiplatform.user`, `modelarmor.user` (added). Topic `tilo-events`: `pubsub.publisher`. `archive`: `objectCreator` (present), `objectViewer` (added). `artifacts` and `snapshots`: `objectCreator`, `objectViewer` (added). `run.invoker` on connectors, browser, render. Receives the Gmail renew and poll calls and the schedule tick from Scheduler | none | mixed |
| `tilo-channels` | Vertex AI (triage, drafting); Model Armor (inbound mail and WhatsApp text); `tilo-api`; the Gmail push endpoint (forwards to the API) | project: custom role `tiloVertexGenerate`, `modelarmor.user` (added). Holds no Firestore, Pub/Sub or Storage role (writes through the API, SEC-12) | `whatsapp-api-token`, `channels-webhook-signing-key`, `email-action-link-signing-key` (channels only, moved from api in P0-07b: links.py issues and verifies; present); `whatsapp-webhook-verify-token`, `channel-binding-hmac-key`, `channel-number-encryption-key`, `webpush-vapid-private-key` (added) | mixed |
| `tilo-connectors` | Firestore (token store, outbox); Cloud KMS; Google Workspace APIs with the user's OAuth token (Gmail, Drive, Calendar, Docs, Sheets, Slides) | project: `datastore.user`. Key `oauth-tokens`: `cryptoKeyEncrypterDecrypter` (added: replaces `cryptoKeyDecrypter`, because `tokens.py` wraps a fresh data key per record). `run.invoker` for harness | `workspace-oauth-client` | mixed |
| `tilo-browser` | Allowlist egress proxy only; model calls for computer use are made by the harness | none (SEC-12: no Firestore, Datastore or Storage) | none | present |
| `tilo-render` | Firestore; `artifacts` bucket; Slides and Docs go through connectors | project: `datastore.user`. Bucket `artifacts`: `objectAdmin` (only service that may overwrite) | none | present |
| `tilo-sandbox-web` | nothing | none | none | present |

Other identities:

| Identity | Grants | Status |
| --- | --- | --- |
| `tilo-tasks-invoker` (Cloud Tasks OIDC) | `run.invoker` on harness | present |
| `tilo-gmail-push` (Pub/Sub push OIDC) | `run.invoker` on channels; Pub/Sub service agent holds `serviceAccountTokenCreator` on it | added |
| `tilo-gmail-scheduler` (Scheduler OIDC) | `run.invoker` on harness only | added |
| `tilo-schedule-scheduler` (Scheduler OIDC, FR-AGT-14) | `run.invoker` on harness only (through `extra_invokers`); no project role, no other grant | added |
| `gmail-api-push@system.gserviceaccount.com` | `pubsub.publisher` on topic `tilo-gmail-notifications` only | added |
| Pub/Sub service agent | custom insert-only role on dataset `tilo_ledger` | present |
| Cloud Storage service agent | `cryptoKeyEncrypterDecrypter` on key `archive` | present |
| `tilo-deployer` (WIF, `refs/heads/main` only) | `run.developer` per service; `serviceAccountUser` per runtime SA; Artifact Registry writer on repo `tilo`. No project role, and `deployer_project_roles` stays `[]` for dev | present |
| `tilo-cloudbuild` (Cloud Build, `cloudbuild.yaml` runs as it; P0-07g) | Five roles, 17 bindings, no key: `roles/artifactregistry.writer` on repo `tilo`; `roles/run.developer` on each of the seven services; `roles/iam.serviceAccountUser` on each of the seven runtime SAs (not tasks-invoker, gmail, deployer or itself); `roles/logging.logWriter` at project level (the only project role); `roles/storage.objectViewer` on bucket `<project>-cloudbuild-staging` | added |
| `tilo-eval-scheduler` (Cloud Scheduler OAuth identity; EFF-05b) | One grant: `roles/run.invoker` on the Cloud Run job `tilo-eval-nightly` only (it includes `run.jobs.run`). No project role, no `serviceAccountUser`, used for nothing else | added |
| `tilo-eval-runner` (runtime identity of the job `tilo-eval-nightly`; EFF-05b) | None. The replay reads files in its image and writes to its log; no secret, no live switch | added |

Bucket `<project>-cloudbuild-staging` (P0-07g): source staging for
`gcloud builds submit --gcs-source-staging-dir`. Regional (`asia-southeast1`),
uniform bucket-level access, public access prevention enforced, one lifecycle
rule deleting objects after 7 days. It is not one of the three PRD buckets
(`storage_buckets` output); the runtime service accounts have no access to it.
`tilo-cloudbuild` only reads it; the person who submits the build writes it
(the project owner already can). Reported by the `cloudbuild_staging_bucket`
output; the grants by `cloudbuild_grants`.

## 3. Pub/Sub, Scheduler, Cloud Tasks

| Resource | Purpose | Status |
| --- | --- | --- |
| Topic `tilo-events` and subscription `tilo-events-to-bigquery` | Ledger (PRD 13.2) | present |
| Topic `tilo-gmail-notifications` | Gmail `users.watch` target (FR-CHN-08) | added |
| Subscription `tilo-gmail-push` | Push to `tilo-channels` `POST /internal/gmail/push`, OIDC as `tilo-gmail-push`, audience = channels URL, no inactivity expiry | added |
| Scheduler `tilo-gmail-renew` (daily 03:00 UTC) | `POST /internal/gmail/renew` on **harness** (re-watch through connectors) | added |
| Scheduler `tilo-gmail-poll` (every 5 min) | `POST /internal/gmail/poll` on **harness** (polling fallback) | added |
| Cloud Tasks queue `runs` | api to harness | present |
| Scheduler `tilo-schedule-tick` (every minute, `* * * * *` UTC, `retry_count` 1) | `POST /internal/schedules/tick` on **harness**, OIDC as `tilo-schedule-scheduler`, audience = harness URL, no body, no query. ONE job for every user schedule (not one per user): the tick reads the due schedules from the store and fires each exactly once per slot (FR-AGT-14) | added |
| Scheduler `tilo-eval-nightly` (daily 19:00 UTC) | OAuth `POST` to the Cloud Run Admin API `.../jobs/tilo-eval-nightly:run`: the replay smoke `python -m tilo_evals nightly` (parallelism 1, one task, 1 retry, 3600 s). Image from `evals/cloudbuild.yaml` (`just build-evals-image`) | added (EFF-05b) |
| Scheduler job for the sweeper | PRD 6.3 | deferred: no sweeper endpoint exists; add with that ticket |

Dependencies (none of these routes exist yet):

- `tilo-channels`: `POST /internal/gmail/push`. `GmailPushEndpoint.receive`
  already verifies the OIDC token (audience = channels URL, email =
  `tilo-gmail-push@<project>.iam.gserviceaccount.com`); the route must call it
  and forward the notification to the API (PRD 6.1: channels write only through
  the API).
- `tilo-harness`: `POST /internal/gmail/renew` and `POST /internal/gmail/poll`.
  Each must check the caller is `tilo-gmail-scheduler@<project>...` (Cloud Run
  already requires `run.invoker`, which only that identity holds besides api and
  the Tasks identity), then call the mailbox through connectors
  (`MailWatcher.renew_due()` / `poll_due()`). Cloud Scheduler may call an
  internal-only service. Channels never reaches connectors.

- `tilo-harness`: `POST /internal/schedules/tick` (FR-AGT-14, built in
  `tilo_harness.app`). It accepts `tilo-schedule-scheduler` only; see the route
  requirements below. Until the Firestore schedule store and the Cloud Tasks run
  starter are wired it answers 503, and the job fires into that 503.

## 4. Storage ownership (PRD 13.2, FR-INT-02)

| Bucket | Writes | Reads | Note |
| --- | --- | --- | --- |
| `artifacts` (versioned, 365 d) | render (`objectAdmin`), api and harness (`objectCreator`) | api, harness (`objectViewer`) | Uploads become new objects, never overwrites |
| `archive` (CMEK, 30 d) | harness (`objectCreator` only) | harness (`objectViewer`, chain check) | Nobody can overwrite or delete |
| `snapshots` (90 d) | harness (`objectCreator`) | harness (`objectViewer`) | |

## 5. Secret Manager slots (names only; values added by the user)

Existing: `workspace-oauth-client`, `whatsapp-api-token`,
`channels-webhook-signing-key`, `email-action-link-signing-key` (channels only). Added:
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
   public callback served by `tilo-api` (`GOOGLE_OAUTH_REDIRECT_BASE_URL`), which
   relays the code to connectors through harness. Connectors is internal-only and
   must never be made public to receive the redirect (PRD 6.5 ingress rule).
2. Put values in the eight secrets (`gcloud secrets versions add`).
3. Identity Platform: enable Google sign-in and anonymous sign-in; add the
   hosting domain to authorised domains.
4. App Check: register the web app with a reCAPTCHA Enterprise key, then switch
   enforcement on for Firestore and Storage after the client sends tokens.
5. Firebase deploys stay manual (the CI deployer holds no project role). From
   the repo root, signed in as yourself (`firebase login`), with `<project>`
   the real project id:

   ```powershell
   firebase deploy --only firestore:rules --project <project>
   pnpm --filter ./apps/web build
   firebase deploy --only hosting --project <project>
   ```

   The hosting deploy targets the project's default Hosting site
   (`https://<project>.web.app`; `firebase.json` has no `site` key). Terraform
   also creates a second site `<project>-web`; nothing deploys to it, and using
   it later means adding `site` to `firebase.json` and updating docs/deploy-dev.md.
   For the dev project, `just deploy-web` runs the web build and hosting deploy
   in one step (docs/deploy-dev.md). Run the rules deploy first.
6. Vertex AI quotas: raise per-minute quotas for the Gemini models in use
   (IAM and Admin, Quotas); Terraform has no resource for them.
7. Model Armor: check `var.model_armor_location` is a supported region the first
   time apply runs; set the template id `tilo-default` in the safety provider
   config.
8. Meta WhatsApp Business: webhook URL, verify token and app secret (stored in
   the secrets above).
9. First Gmail watch: after the endpoints exist, each user's connect flow calls
   `users.watch` with topic `projects/<project>/topics/tilo-gmail-notifications`.

## 8. Decisions taken (orchestrator, on the user's behalf)

1. **channels and connectors.** Only the harness invokes connectors (test
   unchanged); channels gets no VPC egress. Scheduler renew and poll jobs call
   harness; the Gmail push subscription calls channels, which forwards to the
   API. `tilo-gmail-scheduler` therefore holds `run.invoker` on harness, which
   is the one expected invoker set that changed in `cloud_run.tftest.hcl`.
2. **email-action-link-signing-key** is readable by channels only (links.py
   issues and verifies in channels; no api code uses it). The one secret
   expectation edited in `security_iam.tftest.hcl`.
3. **Deployer roles.** None. `deployer_project_roles` defaults to `[]` and is
   not set for dev. Images are built on the CI runner and pushed to Artifact
   Registry through WIF with the repo-scoped writer role, then deployed with
   the per-service `run.developer` grants. The Cloud Build route (P0-07f) runs
   as its own account `tilo-cloudbuild` with five scoped roles and a regional
   staging bucket (P0-07g; section 2, Other identities). Firebase deploys are
   manual (section 7, step 5).

4. **Vertex access for the internet-facing callers.** api and channels hold the
   custom role `tiloVertexGenerate` (permission `aiplatform.endpoints.predict`
   only), not `roles/aiplatform.user`. The provider layer calls
   `generate_content`, `generate_content_stream`, `embed_content` and
   `count_tokens` (`google_adapter.py`). The permission set is UNCONFIRMED: the
   Google reference page could not be fetched in this session (security review:
   it should cover all four calls). Confirm with one smoke call made as
   `tilo-api`; if a call returns 403, add only the permission named in the error
   to the role in `main.tf` and never re-grant `roles/aiplatform.user`. Context
   caching (`aiplatform.cachedContents.*`), batch jobs and Agent Engine would
   need more. Harness keeps `aiplatform.user`; narrow it to a custom role once
   its Sessions, Memory Bank and code-execution calls exist.
5. **Deployer allowlist.** `deployer_project_roles` only accepts
   `cloudbuild.builds.editor`, `firebasehosting.admin`, `firebaserules.admin`;
   anything else fails validation (tested). Default `[]`. Enabling any of them
   needs a fresh security review: `firebaserules.admin` lets CI rewrite
   Firestore rules (it could open all data) and `cloudbuild.builds.editor` can
   run builds as the Cloud Build or default compute service account.
6. **Pub/Sub push token.** The Pub/Sub service agent holds
   `serviceAccountOpenIdTokenCreator` (not full `serviceAccountTokenCreator`) on
   `tilo-gmail-push`.
7. **Model Armor logging.** The template keeps `log_sanitize_operations` and
   `log_template_operations` off (PRD 16.5: screened mail text must not be logged).
8. **Open question: where triage and drafting run (decide before the Gmail
   routes are built).** `triage.py` and
   `drafting.py` live in `tilo-channels` today, so channels holds the model and
   Model Armor grants. If they move to harness, drop channels' model grants
   entirely (`tiloVertexGenerate` and `modelarmor.user`).
9. **Follow-up, not now:** hold `channel-number-encryption-key` as a Cloud KMS
   key instead of a Secret Manager value.

## Route requirements (not built yet; the services must meet these)

Hard requirements from the security review for the routes the infra points at:

- Harness routes check `aud` and the verified email against their own
  allowlist: `/internal/gmail/renew` and `/internal/gmail/poll` accept
  `tilo-gmail-scheduler` only; the Cloud Tasks run route accepts
  `tilo-tasks-invoker` only; 403 otherwise. Claims are read from the validated
  Authorization token only. Renew and poll take no parameters. Why renew and
  poll must refuse `tilo-tasks-invoker`: api holds `run.invoker` on harness and
  can put `tilo-tasks-invoker` OIDC tokens on Cloud Tasks aimed at any harness
  path. Renew and poll reach Gmail only through connectors and iterate the
  stored watches only (`MailWatcher.renew_due` / `poll_due`).
- Schedule tick (`POST /internal/schedules/tick`, built): the route verifies the
  token (`aud` = its own URL, `email` = `tilo-schedule-scheduler@<project>`
  exactly, `email_verified` true) and answers 401 with no token, 403 for any
  other caller (`tilo-gmail-scheduler`, `tilo-tasks-invoker`, `tilo-api` and the
  same name in another project included), 503 when nothing is wired, 200
  `{"fired": n}` otherwise. It reads no body and no query: nothing a caller
  sends selects a schedule or sets the time. Why the gmail and tasks identities
  must be refused: api can put `tilo-tasks-invoker` tokens on Cloud Tasks aimed
  at any harness path, and all three scheduler or tasks identities hold
  `run.invoker` on harness. A run it starts still goes through the outbox and
  the policy engine; every T3 step waits for a person.
- `tilo-channels` is `allUsers`, so the `tilo-gmail-push` `run.invoker` binding
  gives no protection: `/internal/gmail/push` is reachable from the internet and
  no channels route under `/internal/` may rely on ingress or IAM.
- Channels push route (`POST /internal/gmail/push`): full google-auth ID-token
  verification before any parsing, with the claims checked explicitly: `iss` is
  a Google issuer, `email` is `tilo-gmail-push@<project>`, `email_verified` is
  true; the audience equals `module.service.uris['channels']` with no path and
  no trailing slash. `emailAddress` and `historyId` are only a hint: an unknown
  address gets 200 and is ignored, history is read from the stored cursor with
  the user's own token, and there is a per-address rate limit and an alert on the
  volume of ignored pushes. Why: `gmail-api-push@system.gserviceaccount.com` is
  shared by every Gmail account, so anyone can point `users.watch` at our topic;
  do not remove this rule.
- Harness reads of the `archive` bucket stay in deterministic code and never
  become an agent tool.
- Any route that returns a raw archive record enforces world membership and
  `vis`-scope redaction in api first.
- The api artifacts download route checks world membership per object.

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
2. Vertex Sessions, Memory Bank, code execution and Gen AI evaluation are covered by `aiplatform.user` on harness (to be narrowed to a custom role once those calls exist).
3. api and harness store uploads and intermediate artifacts (create and read); only render overwrites.
4. Harness may read `archive` to verify the hash chain; api cannot read it, so the Trace link to a raw record is served by harness (not yet decided in the PRD).
5. Masked screenshots reach Storage through harness, because browser holds no Storage role.
6. Channels binds numbers with an HMAC key and a cipher key held in Secret Manager (the `binding.py` design); the web-push VAPID key is a secret.
7. The push route lives on `tilo-channels` (`/internal/gmail/push`, where `GmailPushEndpoint` is); renew and poll live on `tilo-harness` (`/internal/gmail/{renew,poll}`).
8. Vertex publisher models and Model Armor have no resource-level IAM, so their grants are project-level. The internet-facing services (api, channels) get only the custom `tiloVertexGenerate` role (`aiplatform.endpoints.predict`); harness alone keeps `roles/aiplatform.user`. `roles/modelarmor.user` is project-level for api, harness and channels.
9. The WhatsApp `channels-webhook-signing-key` slot holds the Meta app secret used by `verify_signature`.
