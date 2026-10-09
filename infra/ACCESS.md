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
| `tilo-api` | Firestore (default database only); calls connectors' `/internal/meeting-host/*` with an ID token over its VPC egress (ADR-0032); Cloud Tasks enqueue; Vertex AI (Router: approaches, Director); Model Armor (intake screen); `artifacts` bucket (uploads FR-INT-02, downloads PRD 6.2); Firebase ID-token and App Check verification (public keys, no IAM); the schedule tick (FR-AGT-14): receives the Scheduler call (api is public, the route checks its own Google OIDC token), fetches Google's public certs from googleapis.com through Private Google Access (no IAM), and reads and writes `orgs/{org}/schedules` with the `datastore.user` it already holds | project: `datastore.user` limited by an IAM condition to the (default) database, `cloudtasks.enqueuer`, custom role `tiloVertexGenerate` (`aiplatform.endpoints.predict` only) and `modelarmor.user` (added). Bucket `artifacts`: `objectCreator`, `objectViewer` (added). `serviceAccountUser` on `tilo-tasks-invoker` | none | mixed, see cells |
| `tilo-harness` | Firestore; Cloud Tasks; Vertex AI; Model Armor (model output, tool output); Pub/Sub publish on `tilo-events`; buckets `archive`, `artifacts`, `snapshots`; connectors, browser, render | project: `datastore.user` (default database only, conditioned), `cloudtasks.enqueuer`, `aiplatform.user`, `modelarmor.user` (added). Topic `tilo-events`: `pubsub.publisher`. `archive`: `objectCreator` (present), `objectViewer` (added). `artifacts` and `snapshots`: `objectCreator`, `objectViewer` (added). `run.invoker` on connectors, browser, render. Receives the Gmail renew and poll calls from Scheduler | none | mixed |
| `tilo-channels` | Vertex AI (triage, drafting); Model Armor (inbound mail and WhatsApp text); `tilo-api`; the Gmail push endpoint (forwards to the API) | project: custom role `tiloVertexGenerate`, `modelarmor.user` (added). Holds no Firestore, Pub/Sub or Storage role (writes through the API, SEC-12) | `whatsapp-api-token`, `channels-webhook-signing-key`, `email-action-link-signing-key` (channels only, moved from api in P0-07b: links.py issues and verifies; present); `whatsapp-webhook-verify-token`, `channel-binding-hmac-key`, `channel-number-encryption-key`, `webpush-vapid-private-key` (added) | mixed |
| `tilo-connectors` | Firestore (token store, outbox); Cloud KMS; Google Workspace APIs with the user's OAuth token (Gmail, Drive, Calendar, Docs, Sheets, Slides) | project: `datastore.user` (unconditional: both databases, the only account that reaches `tilo-tokens`). Key `oauth-tokens`: `cryptoKeyEncrypterDecrypter` (added: replaces `cryptoKeyDecrypter`, because `tokens.py` wraps a fresh data key per record). `run.invoker` for harness and for `tilo-api` only (ADR-0032 T5: the meeting-host RPC). One instance max (CON-D9) | `workspace-oauth-client` | mixed |
| `tilo-browser` | Allowlist egress proxy only; model calls for computer use are made by the harness | none (SEC-12: no Firestore, Datastore or Storage) | none | present |
| `tilo-render` | Firestore; `artifacts` bucket; Slides and Docs go through connectors | project: `datastore.user` (default database only, conditioned). Bucket `artifacts`: `objectAdmin` (only service that may overwrite) | none | present |
| `tilo-sandbox-web` | nothing | none | none | present |

Other identities:

| Identity | Grants | Status |
| --- | --- | --- |
| `tilo-tasks-invoker` (Cloud Tasks OIDC) | `run.invoker` on harness. Also the identity of the scheduled-run hand-off (FR-AGT-14e): the tasks `tilo-api` enqueues for its own tick route carry its token, and that route checks it itself (api is public), so no further IAM | present |
| `tilo-gmail-push` (Pub/Sub push OIDC) | `run.invoker` on channels; Pub/Sub service agent holds `serviceAccountTokenCreator` on it | added |
| `tilo-gmail-scheduler` (Scheduler OIDC) | `run.invoker` on harness only | added |
| `tilo-schedule-scheduler` (Scheduler OIDC, FR-AGT-14) | none: no `run.invoker` and no project role. It calls public `tilo-api`, whose tick route verifies the token itself (the first design held `run.invoker` on harness; the tick moved to api with the run, ADR-0023) | added |
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
| Cloud Tasks queue `runs` | api to harness; api to api for scheduled runs (FR-AGT-14e: one task per due slot, delivered to the tick route as `tilo-tasks-invoker`) | present |
| Scheduler `tilo-schedule-tick` (every minute, `* * * * *` UTC, `retry_count` 1) | `POST /internal/schedules/tick` on **api**, OIDC as `tilo-schedule-scheduler`, audience = api URL, no body, no query. ONE job for every user schedule (not one per user): the tick reads the due schedules from the store and hands each to Cloud Tasks exactly once per slot; the run itself executes in the task's own request (FR-AGT-14, FR-AGT-14e) | added |
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

- `tilo-api`: `POST /internal/schedules/tick` (FR-AGT-14b, `tilo_api.schedules`; the
  run lives in tilo-api). It accepts two callers, `tilo-schedule-scheduler` (FR-AGT-14b)
  and `tilo-tasks-invoker` (FR-AGT-14e); see the route requirements below. It answers
  503 until the user sets `TILO_SCHEDULE_TICK_AUDIENCE` (copy the `audience` field of
  `terraform output schedule_tick`), `TILO_SCHEDULE_TICK_CALLER`, `TILO_TASKS_CALLER`
  (`tilo-tasks-invoker@<project>.iam.gserviceaccount.com`), `TILO_RUNS_QUEUE`
  (`projects/<project>/locations/asia-southeast1/queues/runs`),
  `TILO_SCHEDULES_STORE=firestore` and `TILO_FIRESTORE_PROJECT` on tilo-api AND
  production wires the api store and run seams (they answer 503 when deployed today);
  the job fires into that 503 until then. The earlier harness route stays unused (to
  be removed in a later ticket).

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

1. OAuth consent screen: add the scopes above and set the app to In production
   (the user's decision, BQ-SIGNIN-1; Testing with up to 100 test users is the
   fallback, section 11 step 6). Create the web OAuth client; set its redirect URI to the
   public callback served by `tilo-api` (`GOOGLE_OAUTH_REDIRECT_BASE_URL`), which
   relays the code to connectors through harness. Connectors is internal-only and
   must never be made public to receive the redirect (PRD 6.5 ingress rule).
2. Put values in the eight secrets (`gcloud secrets versions add`).
3. Identity Platform: enable Google sign-in and anonymous sign-in; add the
   hosting domain to authorised domains.
4. App Check (SEC-10): done in the console, recorded here. The Firebase web app
   `tilo-web` has app id `1:379216745263:web:8cda5846cf882c2cefc7da` and the
   reCAPTCHA Enterprise score-based site key is
   `6LdlsOItAAAAAEhO_aq9zmtbQue6Rni2ZDUDuRTe`. Both ids are public values (the web
   client ships them, `apps/web/src/appcheck/config.ts`), not secrets. The web
   `apiKey` and `projectId` are not in the repo either: the deploy build reads
   them from `firebase apps:sdkconfig` (docs/deploy-dev.md). The browser `apiKey`
   is "public" only if it is restricted: it is baked into the public bundle, and
   this project also uses Gemini Developer API keys. OWNER STEP, BEFORE the first
   `just deploy-web` that bakes the key in: in the Google Cloud console
   (APIs and Services, Credentials) open the Firebase web key and (a) set an API
   restriction to exactly three APIs: Firebase App Check API, Identity Toolkit API
   and Token Service API (the last two are what Google sign-in calls, section 11),
   (b) set website restrictions
   to the referrers `https://essential-wares-510320-f0.web.app/*` and
   `https://essential-wares-510320-f0.firebaseapp.com/*`, (c) confirm it cannot
   call `generativelanguage.googleapis.com` or any other paid API. Only then run
   `just deploy-web` with `TILO_BAKE_FIREBASE_KEY=1` set; without that variable
   the recipe builds with no Firebase config and App Check is skipped. Enforcement is OFF
   everywhere and stays off until the owner switches it on: in `tilo-api` by
   `TILO_APPCHECK_ENFORCE=1` on the Cloud Run service, and for Firestore and
   Storage in the Firebase console, only after the deployed client sends tokens
   and the API log shows none refused.
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

1. **channels and connectors.** Harness and, since ADR-0032 T5, `tilo-api`
   (the meeting-host RPC) invoke connectors; no one else (`cloud_run.tftest.hcl`
   pins exactly those two, one instance); channels gets no VPC egress. Scheduler renew and poll jobs call
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
- Schedule tick (`POST /internal/schedules/tick` on **tilo-api**, built): api is public (`allUsers`), so
  neither ingress nor IAM protects the route and it checks its caller itself; it verifies the
  token (`aud` = its own URL, `email` exactly, `email_verified` true; a malformed token is
  refused before any call to Google's cert endpoint) and answers 401 with no token, 403 for
  any other caller (`tilo-gmail-scheduler`, `tilo-api` and the same names in another
  project included), 503 when nothing is wired. It has TWO callers and the identity picks
  the mode (FR-AGT-14e, BQ-AGT14-5): (1) `tilo-schedule-scheduler@<project>` (the exact
  `TILO_SCHEDULE_TICK_CALLER`) with NO body fans out: it claims each due slot and hands it
  to Cloud Tasks (`TILO_RUNS_QUEUE`), starts nothing, and answers 200 `{"fired": n}`;
  (2) `tilo-tasks-invoker@<project>` (the exact `TILO_TASKS_CALLER`) with the task's JSON
  body runs ONE run inside that request, so CPU is allocated while it works, and answers
  200 `{"ran": 1, "state": "done" | "parked" | "timeout"}` or a 2xx `{"ran": 0, "skipped": code}`
  for a refusal. The Scheduler never gets the Tasks mode and Cloud Tasks never gets the
  Scheduler's: the Scheduler with a body, the Tasks identity without one, and one account
  configured for both are refused with no side effect. The task body is untrusted (closed,
  strict; the owner, brief and cap come from the stored schedule only). Why only these two:
  any Google service account can mint a token with the api audience, so only the two named
  accounts pass. A run it starts still goes through the outbox and the policy engine; every
  T3 step waits for a person. No Terraform change: `tilo-api` (like `tilo-harness`) already holds
  `cloudtasks.enqueuer` and `serviceAccountUser` on `tilo-tasks-invoker`, so either can mint a
  task token for this route (an accepted trust set, BQ-AGT14-5 h), and api needs no
  `run.invoker` for a task to reach it. The api service's request timeout must cover the
  in-request wait (1500 s): see `infra/README.md`.
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

## 11. Sign-in with Google (Firebase Authentication): the console checklist (SEC-15)

Terraform cannot do these. They turn on app sign-in (Google, and anonymous demo sessions for visitors and judges), which
`tilo-api` checks on every request and the web app asks for before it shows anything (BQ-SIGNIN-1..7 in
`docs/open-questions.md`). Tilo never handles passwords (PRD 16.1). Do them in this order, for project
`essential-wares-510320-f0`:

1. Firebase console, Authentication, Get started.
2. Authentication, Sign-in method: enable the Google provider (public-facing name `Tilo`, your support email) and save.
3. Authentication, Sign-in method: enable the Anonymous provider (demo sessions). Never enable Email/Password or any other
   provider: Tilo never handles passwords.
4. Authentication, Settings, Authorized domains: check `essential-wares-510320-f0.web.app` and
   `essential-wares-510320-f0.firebaseapp.com` are listed (they are by default; add them if not), and remove `localhost`
   if it is there (Firebase adds it by default; the deployed project must not accept sign-ins started from a local page).
5. Google Cloud console, APIs and Services, Credentials, the Firebase web key (the one step 4 of section 7 restricted):
   set the API restriction to exactly three APIs: Firebase App Check API, Identity Toolkit API and Token Service API.
   The Auth SDK calls `identitytoolkit.googleapis.com` and `securetoken.googleapis.com`, and Google refuses sign-in
   with the key restricted to App Check alone. Keep the website restrictions (the two referrers); the key must still not
   reach `generativelanguage.googleapis.com` or any other paid API.
6. Google Cloud console, Google Auth Platform (OAuth consent screen), Audience: publishing status In production.
   The user's decision (7 Oct 2026, BQ-SIGNIN-1) is In production, so the status is not a choice you make here.
   The sign-in scopes `openid`, `email` and `profile` are non-sensitive (basic), so anyone with a Google account can
   sign in: no test-user list, no expiry. The Gmail scopes (`gmail.readonly`, `gmail.compose`, `gmail.send`) are
   restricted, so Google shows its unverified-app warning on every Gmail consent and caps an unverified app at
   100 new users until Google verifies those scopes; the Gmail consent sheet (S-08) says so before the redirect. No code
   path depends on the status, so either works. Fallback in one line: set it back to Testing and list test users; sign-ins and grants then expire after
   about 7 days (PRD R-06).
7. Later, an owner step, not needed to sign in: start Google verification for the restricted Gmail scopes
   (Google Auth Platform, Verification Center), once the app is ready to be reviewed. Until it is approved the
   unverified-app warning and the cap stay.
8. Redeploy hosting (the Content-Security-Policy and the sign-in code ship together): `just deploy-web` with
   `TILO_BAKE_FIREBASE_KEY=1`, then sign in on `https://essential-wares-510320-f0.web.app` and check the browser
   console shows no Content-Security-Policy violation, before telling anyone to sign in. Also check that the
   site-wide `frame-ancestors 'none'` and `X-Frame-Options` (rule source `**` in `firebase.json`) do not break the
   sign-in iframe Firebase serves at the reserved path `/__/auth/iframe`: if the popup sign-in fails or the console
   shows a refused frame, exempt `/__/auth/**` from those two headers (a separate headers rule), and re-check.

After the founder has signed in once with Google, `TILO_PEOPLE_BOOTSTRAP_UID` on `tilo-api` must hold the id the API gives
that person, which is not the Firebase uid: copy the uid (Firebase console, Authentication, Users, "User UID") and run
`uv run python scripts/signin_user_id.py <uid>`; the printed `u_...` value goes in the variable (BQ-SIGNIN-9). Before
`TILO_JUDGE_LIVE=1` is ever set, read BQ-SIGNIN-9 and BQ-SIGNIN-10: an anonymous demo session already gets replay models
only, and App Check enforcement on Firebase Authentication is worth considering, since anonymous uids are free.

## 9. Token database and connectors settings (ADR-0032 T5)

Firestore IAM conditions name a database, never a collection, so project-wide `datastore.user` could not exclude
`connector_tokens`. Tokens move to the database `tilo-tokens`; api, harness and render keep `datastore.user` only on
`(default)` (condition `default-database-only`); connectors holds it unconditionally. `security_iam.tftest.hcl` pins
this. Rules: a database with no rules deployed denies clients, and no allow rule exists (T5b adds a tokens rules file).

Connectors `TILO_*` settings are set by hand (`ignore_env`, like api). The ordered steps and values: `docs/deploy-dev.md`
("Meeting host: connectors and api settings").
