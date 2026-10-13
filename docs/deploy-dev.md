# Deploy to tilo-dev (P0-07a, P0-07c)

## User's one sitting (about 10 min)

Copy and paste in this order, from the repository root. Services deploy with Google Cloud Build (P0-07f), so
no GitHub variable, no merge to `main` and no `gh` sign-in is needed. Tilo's tooling runs none of these.

1. Put the Cloud Build identity and its staging bucket in place (P0-07g). You run the infrastructure apply, in
   `infra/envs/dev` (Tilo's tooling never does). Do it first: until it is done, every Cloud Build deploy fails before
   any step runs. Use the project's usual steps from `infra/README.md`: sign in and the application-default login
   (its steps 1 and 2), `init` against your `backend.hcl` (step 7), then the plan with your four `-var` values saved
   to `tfplan` (step 8). Plan first and read it before you continue: expect about 19 to add (the `tilo-cloudbuild`
   service account, 7 `run.developer` bindings, 7 `serviceAccountUser` bindings, 1 Artifact Registry writer binding,
   1 `logging.logWriter` project binding, the bucket `essential-wares-510320-f0-cloudbuild-staging` and its
   `objectViewer` binding), 0 to change, 0 to destroy. If the plan shows any destroy, stop and ask. Then run the
   apply step in `infra/README.md` (step 9) on that saved plan.

2. Sign in to Google Cloud as yourself (opens a browser) and point `gcloud` at the tilo-dev project:

   ```powershell
   gcloud auth login
   gcloud config set project essential-wares-510320-f0
   ```

   Use the Google account that owns the project. If `gcloud` is not installed, install the Google Cloud CLI first.
   The project owner can write the staging bucket and act as `tilo-cloudbuild`; any other account needs
   `roles/storage.objectCreator` on `gs://essential-wares-510320-f0-cloudbuild-staging`,
   `roles/cloudbuild.builds.editor` and permission to act as `tilo-cloudbuild`.

3. Web app on Firebase Hosting (opens a browser for your own Google sign-in; use the account that has Firebase
   access on project `essential-wares-510320-f0`, any other account fails with a permission error):

   ```powershell
   pnpm install
   pnpm exec firebase login
   just deploy-web
   ```

   Result: https://essential-wares-510320-f0.web.app (the default Hosting site).

4. Deploy the services, API first, check it, then everything:

   ```powershell
   just deploy-dev-cloudbuild api
   just deploy-dev-cloudbuild all
   ```

   Each call uploads the repo to `gs://essential-wares-510320-f0-cloudbuild-staging/source` (`.gcloudignore` keeps
   secrets and VCS data out), builds in `asia-southeast1` and prints the build log. The seven services are `api`,
   `harness`, `channels`, `connectors`, `browser`, `render`, `sandbox-web`.

5. What to expect: `tilo-api` fails closed without a principal (a request with no sign-in is refused;
   that is correct, not a bug). Cloud Build does not smoke test: look at the services in the Cloud Run console, or
   run `gcloud run services describe tilo-api --region asia-southeast1` and check the Ready condition.

The web app and the services are independent: step 3 needs no build, and the services need no Hosting deploy.

How the seven Cloud Run services and the web app reach `tilo-dev`. Region `asia-southeast1`. This
runbook is for `tilo-dev` only: nothing here ever targets `tilo-demo` (that deploy is a separate,
user-approved step, never from this workflow or recipe).

## What deploys what

`just deploy dev` (also `just deploy env=dev`) deploys existing dev services through
Cloud Build: API first, then all services. If the API build fails, the second build
does not start. Non-dev arguments are rejected before any shell runs. This entry
point does not apply infrastructure or deploy Hosting; use the web recipe below
for Hosting. GitHub Actions remains unused under the current user policy.

| Piece | How | Where it is defined |
| --- | --- | --- |
| Services `tilo-api`, `tilo-harness`, `tilo-channels`, `tilo-connectors`, `tilo-browser`, `tilo-render`, `tilo-sandbox-web` | Google Cloud Build: `just deploy-dev-cloudbuild` runs `cloudbuild.yaml` (P0-07f). Alternative: `.github/workflows/deploy-dev.yml` (`workflow_dispatch` only). Both build `services/<svc>/Dockerfile` with the repo root as context | PRD 6.2, 6.5 |
| Web app (`apps/web`) | Firebase Hosting, by hand (below). The CI deployer has no Firebase role by design | `firebase.json` |
| Infrastructure (services, IAM, ingress, env, secrets) | Terraform, applied by you (`infra/README.md`) | `infra/` |

Cloud Build and the workflow only swap the image (pinned by digest) and passes `--min-instances 0` and
`--max-instances` (harness and channels 3; connectors = 1 until T7; browser, render and sandbox-web 2;
`tilo-api` 1: one instance is the one writer, ADR-0026) on an existing service. It never sets ingress, IAM, env vars or secrets;
Terraform owns those and ignores image changes (`infra/modules/service`). Env vars are Terraform's for every service
except `tilo-api` and `tilo-connectors`: those have `ignore_env = true`, so their `TILO_*` runtime settings are set by hand with
`gcloud run services update` (`docs/routines-rollout.md`) and a Terraform run leaves them alone.

## Alternative: GitHub Actions workflow (one-time setup)

Only needed if you prefer the Actions route to Cloud Build. The sections up to "Web app" describe it.

Setup, once, after the infrastructure is in place:

1. In the GitHub repository `spark-456/tilo`, open Settings, Secrets and variables, Actions, Variables
   (repository variables, not secrets) and add:
   - `GCP_PROJECT_ID`: the tilo-dev project id (`terraform output` or your project list).
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`: the provider resource name
     `projects/<project number>/locations/global/workloadIdentityPools/tilo-github/providers/github`.
   - `GCP_DEPLOYER_SERVICE_ACCOUNT`: `terraform output deployer_service_account_email`
     (`tilo-deployer@<project id>.iam.gserviceaccount.com`).
2. Nothing else: no key file, no secret. Authentication is Workload Identity Federation, and the
   provider accepts tokens only from this repository on `refs/heads/main`
   (`infra/modules/wif`). A run from any other ref or a fork fails before any step runs.

Current dev values (infra is applied): project `essential-wares-510320-f0`, deployer
`tilo-deployer@essential-wares-510320-f0.iam.gserviceaccount.com`. They live only in the repository
variables above, never in the workflow or the recipe.

The WIF provider's attribute condition allows only `assertion.ref == "refs/heads/main"`. So the deploy
waits for `phase0-stack` to merge into `main` (the orchestrator moves `main`); until then dispatch cannot
authenticate. The one-line infra alternative (also trusting `refs/heads/phase0-stack`) is a change you would
apply yourself and is not recommended.

The deployer (`tilo-deployer`) holds exactly: `roles/run.developer` on each of the seven services,
`roles/iam.serviceAccountUser` on each runtime service account, and `roles/artifactregistry.writer` on
the Artifact Registry repository `tilo`. No project-level role. See `infra/ACCESS.md`.

## Deploy with the Actions workflow

```powershell
just deploy-dev          # refuses any env other than dev; needs `gh` signed in
```

This runs `gh workflow run deploy-dev.yml --ref main`. Or open Actions, deploy-dev, Run workflow, branch
`main`, and optionally pick one service (default `all`). Merge to `main` first: the workflow runs the
code on `main`, and every job is guarded on `spark-456/tilo` and `refs/heads/main`.

The run: build each image on the runner, push to
`asia-southeast1-docker.pkg.dev/<project>/tilo/<svc>:<commit sha>`, update `tilo-<svc>` to that image digest,
then smoke test. Smoke reads each service's URL from `gcloud run services describe` and checks the Ready
condition. Services with public ingress (api, channels, sandbox-web) also get `curl --fail` on `/health`
(every service answers it with `{"status":"ok"}`; `/healthz` is kept for in-container probes only, because Cloud Run
reserves it on `run.app` URLs and never forwards it to the container).
Internal-only services (harness, connectors, browser, render) cannot be reached from a runner and the
deployer holds no `run.invoker`, so they get the Ready check only. A real HTTP check of those needs an
in-VPC probe or a wider role: your decision (docs/p0-07a-notes.md, item 7).

To roll back, revert on `main` and dispatch again (the workflow always runs `main`), or send traffic to a
previous revision in the Cloud Run console.

## Deploy with Cloud Build (P0-07f)

```powershell
gcloud auth login
gcloud config set project essential-wares-510320-f0
just deploy-dev-cloudbuild api     # one service first
just deploy-dev-cloudbuild all     # then everything (the default)
```

`just deploy-dev-cloudbuild service="all" env="dev"` refuses any env other than dev, then runs
`gcloud builds submit --config cloudbuild.yaml --project essential-wares-510320-f0 --substitutions "_SERVICE=<service>" --region asia-southeast1 .`.
The tilo-dev project is pinned in the recipe (no parameter or `gcloud config` value can change it), `env` must be
`dev`, and `service` must be `all` or one of the seven names: `just` checks both before any shell runs, so
a flag or a shell command cannot be smuggled in through them.
`cloudbuild.yaml` (repo root) has three steps: check `_SERVICE` (`all` or one of the seven short names, anything
else fails with `unknown service`), build each image from `services/<svc>/Dockerfile` with the repo root as
context and push it to `asia-southeast1-docker.pkg.dev/<project>/tilo/<svc>:<build id>`, then
`gcloud run services update tilo-<svc> --image <repo>@sha256:<digest> --min-instances 0 --max-instances <n>` (`tilo-api` is always `--max-instances 1`, ADR-0026; connectors stays 1 until T7, the others 2 or 3),
after refusing any image reference that is not `asia-southeast1-docker.pkg.dev/<project>/tilo/<svc>@sha256:...`.
The upload is an allowlist (`.gcloudignore`): only `pyproject.toml`, `uv.lock`, `.dockerignore`, `evals/pyproject.toml`
and the `packages`, `services`, `config`, `contracts`, `prompts` and `templates` trees leave your machine, and secret
and state files (`.env*`, keys, `client_secret*.json`, `token*.json`, `*.tfplan`, `*.tfstate*`) are excluded inside them.
The project id is Cloud Build's `$PROJECT_ID`, never written in the file. The recipe uploads the source with
`--gcs-source-staging-dir gs://essential-wares-510320-f0-cloudbuild-staging/source` (below), so it lands in a regional
bucket instead of the US multi-region bucket `gcloud` would create on its own. Nothing else is touched: no ingress, IAM,
env vars or secrets. The build runs as the dedicated account `tilo-cloudbuild` (below). It times out at 2700 s (the 45 minute cap of the workflow), logs
go to Cloud Logging only, and the builder images are pinned and listed in `docs/licences.md`.

Rollback: send traffic to a previous revision in the Cloud Run console, or revert and run the recipe again.

### IAM the Cloud Build service account needs (Terraform, P0-07g, applied by you)

`cloudbuild.yaml` sets its top-level `serviceAccount` field to
`projects/$PROJECT_ID/serviceAccounts/tilo-cloudbuild@$PROJECT_ID.iam.gserviceaccount.com`
(`tilo-cloudbuild@<project id>.iam.gserviceaccount.com`), so every build runs as that dedicated account, which holds
only the five roles below and has no key. Never grant them to the Compute Engine default service account or to the
legacy Cloud Build account (`<project number>@cloudbuild.gserviceaccount.com`): those are shared identities that
every other build, VM or function inherits, and on many projects the Compute Engine default account holds a broad
editor role already (inferred from Google's defaults, not checked on this project). Pinning `tilo-cloudbuild` is what
keeps the build to these five grants.

The separate Terraform PR (P0-07g, `infra/envs/dev/main.tf`) creates `tilo-cloudbuild`, the five roles below (17 bindings) and the
staging bucket. They exist only after you have run the apply step (see "User's one sitting", step 1); until then the
build fails before any step runs and nothing is built or deployed.

Roles for `tilo-cloudbuild`, scoped the way the deployer's access is:

- `roles/artifactregistry.writer` on the Artifact Registry repository `tilo` (not project-wide).
- `roles/run.developer` on each of the seven services `tilo-<svc>` (per service, never project-wide). It cannot set
  IAM, so invoker bindings stay with Terraform.
- `roles/iam.serviceAccountUser` on each of the seven runtime service accounts (the updated revision runs as them).
- `roles/logging.logWriter` at project level (Google offers no narrower scope), so `CLOUD_LOGGING_ONLY` works.
- `roles/storage.objectViewer` on the bucket `essential-wares-510320-f0-cloudbuild-staging` only, so the build can
  read the upload. It cannot write there: with `CLOUD_LOGGING_ONLY` the build writes no log object.

The staging bucket `essential-wares-510320-f0-cloudbuild-staging` (Terraform-managed) is regional
(`asia-southeast1`), has uniform bucket-level access and enforced public access prevention, and deletes objects after
7 days (uploaded source is disposable). The runtime service accounts have no access to it.

You, as the person running `gcloud builds submit`, need write access to that bucket (`roles/storage.objectCreator`
on it), `roles/cloudbuild.builds.editor` and permission to act as `tilo-cloudbuild` (the project owner has all of
these).

### Known gaps of the Cloud Build identity (not fixed here)

- The first update of `tilo-api` or `tilo-harness` (both use Direct VPC egress) may fail with a 403: changing a
  revision that uses a VPC subnet can need `compute.subnetworks.use` (for example `roles/compute.networkUser` on that
  subnet) for the caller. This is unverified until the first real deploy. If it happens, the fix is a separate,
  subnet-scoped grant (never project-wide), reviewed on its own.
- `run.developer` plus `serviceAccountUser` lets the build re-point a service to run as any of the seven runtime
  service accounts. Both are needed to deploy and are limited to those seven accounts; the `cloudbuild.yaml`
  allowlist and Cloud Audit Logs are the controls. Closing it fully needs a deploy path that fixes each service's
  runtime account, which is a later decision.

## Nightly eval smoke (EFF-05b, Cloud Scheduler)

Cloud Scheduler `tilo-eval-nightly` (daily 19:00 UTC) starts the Cloud Run job `tilo-eval-nightly`, which runs
`python -m tilo_evals nightly` (replay; no secret, no live switch). `infra/envs/dev/eval_nightly.tf` creates it with two
new service accounts (`tilo-eval-scheduler`: `roles/run.invoker` on that one job; `tilo-eval-runner`: no role).
Order: build the image first (`just build-evals-image`, Cloud Build as `tilo-cloudbuild`, pushes `tilo/evals:latest`);
then check the Terraform offline with `just tf-validate` (`terraform init -backend=false` and `terraform validate`
in `infra/envs/dev`; it downloads providers but needs no credentials and changes nothing); then plan and apply as in
`infra/README.md`. Expect exactly 6 to add (google_service_account.eval_scheduler, google_service_account.eval_runner,
google_cloud_run_v2_job.eval_nightly, its google_cloud_run_v2_job_iam_member, google_cloud_scheduler_job.eval_nightly, and
module.monitoring.google_monitoring_alert_policy.eval_nightly_failed, EFF-05c), 1 to change (the Artifact Registry
repository `tilo` gains two cleanup policies, in place, for the `evals` package only: keep the newest 5 versions, delete
older ones after 7 days), 0 to destroy; any destroy means stop and ask. The alert emails `alert_email` when an execution of
the job finishes as failed. Test the job once with
`gcloud run jobs execute tilo-eval-nightly --region asia-southeast1 --project essential-wares-510320-f0 --wait`
and read the job log in Cloud Logging. The job fails until the `nightly` command (EFF-05a) is in the image.

## Scheduled runs (FR-AGT-14, Cloud Scheduler + Cloud Tasks)

Routines need the runs queue, the `tilo-schedule-tick` Scheduler job and six `tilo-api` settings. The steps, the
checks and what each tick answer means are in [routines-rollout.md](routines-rollout.md).

## Meeting host: connectors and api settings (ADR-0032 T5)

Order, once your infrastructure run (`infra/README.md`) has finished (run it with no run in flight):
0. Smoke: api, harness and render must still read Firestore `(default)` (a schedule tick or a run answers, not 503). That
   proves the `resource.name` condition on their `datastore.user`.
1. The KMS key `oauth-tokens` is Terraform's (`module.kms`); never create it by hand. Put the OAuth client id and secret
   in the Secret Manager secrets `workspace-oauth-client-id` and `workspace-oauth-client-secret` (one version each).
2. Set `tilo-connectors` (names here, never a value in a file or a log). `<url>` is its own URL.
   `TILO_CONNECTORS_AUDIENCE=<url>`, `TILO_MEETING_HOST_CALLER=tilo-api@<project>.iam.gserviceaccount.com`,
   `TILO_TOKEN_STORE=firestore`, `TILO_FIRESTORE_PROJECT=<project>`, `TILO_TOKEN_DATABASE=tilo-tokens`,
   `TILO_KMS_KEY=projects/<project>/locations/asia-southeast1/keyRings/<ring>/cryptoKeys/oauth-tokens`, the OAuth client
   id and secret as Secret Manager references (`--update-secrets`, which keeps the others; secret
   `workspace-oauth-client-id` and `-secret`), and no `LIVE`.
   Connectors runs one instance (CON-D9) until ticket T7.
3. Set `tilo-api`: `TILO_CONNECTORS_URL=<tilo-connectors url>`. api reaches the internal service through its Direct VPC
   egress, and holds `run.invoker` on connectors.
4. `LIVE=1` on connectors only, and the first live invitation, are yours after T7. Connectors (T5b) builds its Firestore
   client on `TILO_TOKEN_DATABASE` and refuses to start the broker without it: unset, `(default)` or any malformed id
   is refused, so tokens never land in `(default)`. Order: apply the infrastructure first (it creates `tilo-tokens`, its
   deny-all ruleset and the release `cloud.firestore/tilo-tokens`), then set the variable, then deploy the T5b image.

## Live connectors: OAuth client, index, settings (ADR-0035 L7, L8)

Gmail, Drive and Calendar go live through `tilo-connectors` only. Do the steps in this order; Tilo's tooling runs none of
them. Terraform adds one Firestore composite index and two empty Secret Manager secrets (`workspace-oauth-client-id`,
`workspace-oauth-client-secret`), each readable by `tilo-connectors` only (BQ-ADR35-L7-1). Both services have `ignore_env`, so the settings are `gcloud` steps, and a Terraform run leaves them.

1. Create the OAuth client and consent screen (`infra/ACCESS.md` section 13). Keep the client id and client secret to
   hand; do not paste them into a command line, a file or chat.
2. Apply the infrastructure (`infra/README.md`). Expect exactly 5 to add, 0 to change, 0 to destroy: the index
   `google_firestore_index.outbox_transfer_pending` (collection `outbox`, `transfer_pending` ASC, `enqueued_at` ASC), the
   secrets `workspace-oauth-client-id` and `workspace-oauth-client-secret`, and one `secretAccessor` binding on each
   (`tilo-connectors`). Then add ONE version to each secret, in the Secret Manager console (Add new version, paste the
   value), or with `gcloud secrets versions add workspace-oauth-client-id --project $P --data-file=-`: type or paste the
   value on the next line, then Ctrl+Z and Enter. Never put the value in the command line (it lands in history).
   **The index must be built (state READY, a few minutes: Firestore console, Indexes) before `TILO_OUTBOX_STORE=firestore`
   is set.** Without it, claiming a transfer raises 503 after an entry was sent (PI-17).
3. Run the outbox store suite once against the Firestore emulator (needs Java and `pnpm install`; no cloud credential):

   ```powershell
   pnpm exec firebase emulators:exec --only firestore --project demo-tilo "uv run pytest -q services/api/tests/test_FR_CON_02_ADR35_L2_outbox_store_contract.py"
   ```

4. Set `tilo-connectors`. `^#^` makes `#` the separator, because the account email holds `@`; every value is quoted:

   ```powershell
   $P = "essential-wares-510320-f0"; $R = "asia-southeast1"
   $Conn = gcloud run services describe tilo-connectors --project $P --region $R --format "value(status.url)"
   gcloud run services update tilo-connectors --project $P --region $R `
     --update-env-vars "^#^GOOGLE_OAUTH_REDIRECT_BASE_URL=https://essential-wares-510320-f0.web.app#TILO_TOKEN_STORE=firestore#TILO_FIRESTORE_PROJECT=${P}#TILO_TOKEN_DATABASE=tilo-tokens#TILO_KMS_KEY=projects/${P}/locations/${R}/keyRings/tilo-${R}/cryptoKeys/oauth-tokens#TILO_CONNECTORS_AUDIENCE=${Conn}#TILO_MEETING_HOST_CALLER=tilo-api@${P}.iam.gserviceaccount.com" `
     --update-secrets "GOOGLE_OAUTH_CLIENT_ID=workspace-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=workspace-oauth-client-secret:latest"
   ```

   `LIVE` stays unset. `--update-*` keeps every other setting. Connectors stays at one instance (ADR-0032 T7).
5. Confirm the outbox index is READY first (step 2), then set `tilo-api` (same PowerShell session as step 4: `$P`, `$R` and
   `$Conn` are reused; `TILO_API_STORE` and `TILO_PEOPLE_STORE` stay out: the separate ADR-0026 rollout):

   ```powershell
   $Conn = gcloud run services describe tilo-connectors --project $P --region $R --format "value(status.url)"
   gcloud run services update tilo-api --project $P --region $R `
     --update-env-vars "^#^TILO_OUTBOX_STORE=firestore#TILO_CONNECTORS_URL=${Conn}"
   ```

6. Deploy the images (`just deploy-dev-cloudbuild connectors`, then `api`) and `just deploy-web` if the web app changed. The
   Hosting headers for `/oauth/google/callback` are already in `firebase.json`.
7. Your go. Then `LIVE=1` on connectors only: `gcloud run services update tilo-connectors --project $P --region $R --update-env-vars "LIVE=1"`.
   Never on `tilo-api`. To switch off, `--remove-env-vars "LIVE"`.
8. Acceptance (L8) with `tilotesting@gmail.com`: connect Gmail read, then Drive and Calendar write; a draft appears; a send to
   the same address arrives once; a file lands in the Tilo folder; an event appears and a cancelled one does not; disconnect
   leaves no Tilo access in the Google account. Testing mode expires a grant after 7 days (PRD 11.5): connect again.

## Web app (Firebase Hosting, manual; P0-07c)

```powershell
pnpm install
pnpm exec firebase login      # once: you sign in with your own Google account (browser)
just deploy-web
```

`just deploy-web` builds `apps/web` with `VITE_TILO_API_URL` set to empty, then runs
`pnpm exec firebase deploy --only hosting --project essential-wares-510320-f0`. Its one optional
argument is a tilo-api url (next section); the project id is fixed in the recipe, so it refuses every other
project by construction. The
`firebase-tools` CLI is an `apps/web` devDependency, so no global install is needed. The result is
live at https://essential-wares-510320-f0.web.app (and the `.firebaseapp.com` alias).

- Fixture / replay world: with `VITE_TILO_API_URL` unset the deployed web app uses the in-browser
  `FixtureClient`; it replays the recorded world and makes no call to any backend. Pointing it at a
  deployed `tilo-api` is a later step (set the variable at build time), not part of this deploy.
- The CI deployer has no Firebase role, so Hosting is never deployed from Actions: this is a manual
  step by you. Tilo's tooling never handles passwords or tokens; `firebase login` is yours.
- `firebase.json` serves `apps/web/dist` with a single-page-app rewrite to `/index.html` for everything
  except `/assets/**` (`!/assets/**`, so a stale tab asking for a removed hashed asset gets a plain 404
  instead of `index.html`; any path with a dot segment such as `/.x` or `/.well-known/x` is rewritten to the
  non-existent `/404.html` and so also 404s, because a `**` glob skips dot segments and would leave the shell
  without security headers), hashed files under `/assets/**` as `public, max-age=31536000, immutable`, and
  every other path as `no-cache` (the `**` default) so a new deploy is picked up on the next load. Every
  route also gets `Content-Security-Policy` (self only, no inline styles, `base-uri 'none'`,
  `frame-ancestors 'none'`, no `unsafe-eval`: the web app loads `pixi.js/unsafe-eval`; SEC-10 adds exactly
  `https://www.google.com/recaptcha/` and `https://www.gstatic.com/recaptcha/` to `script-src`,
  `https://www.google.com/recaptcha/` to `frame-src` and `https://content-firebaseappcheck.googleapis.com`
  (the host the web SDK, `@firebase/app-check` 0.13.1, exchanges tokens at) plus `https://www.google.com/recaptcha/`
  (reCAPTCHA Enterprise's own `enterprise/clr` fetch) to `connect-src`, for App Check with
  reCAPTCHA Enterprise), `X-Content-Type-Options: nosniff` and
  `Referrer-Policy: strict-origin-when-cross-origin`. A new backend origin for the web app must be
  added to `connect-src` when the app is pointed at a deployed `tilo-api`.
- Two Hosting sites exist in the project: the default site `essential-wares-510320-f0`
  (https://essential-wares-510320-f0.web.app, the one this deploy targets, so `firebase.json` has no
  `site` key) and the Terraform-created `essential-wares-510320-f0-web`
  (https://essential-wares-510320-f0-web.web.app). The `-web` site is optional and unused.
- Check before you deploy: `pnpm --filter @tilo/web run build` then `pnpm --filter @tilo/web exec vite preview`
  serves the same bundle locally.

## Test the live world on tilo-dev

The deployed web app (Hosting) can talk to the deployed `tilo-api` (https://tilo-api-4qhkpsn5ga-as.a.run.app) with
`just deploy-web-live` (WEB-TO-API). `just deploy-web` stays the fixture build. Your own steps, in order; Tilo never
runs them for you and never handles your password:

1. In the Cloud console (APIs & Services, Credentials), restrict the Firebase browser API key BEFORE it is baked in:
   API restrictions to exactly three APIs (Firebase App Check, Identity Toolkit and Token Service), website restrictions to
   `https://essential-wares-510320-f0.web.app/*` and `https://essential-wares-510320-f0.firebaseapp.com/*`
   (infra/ACCESS.md section 7). The key ends up in the public JavaScript bundle.
2. `pnpm exec firebase login` (once, your own Google account).
3. Set the tilo-api settings with `gcloud run services update`. The 7 `TILO_*` settings are step 2 of
   `docs/routines-rollout.md`. `LIVE`, `TILO_API_DEV` and `TILO_JUDGE_LIVE` stay unset. The CORS origins contain a
   comma, so use gcloud's custom delimiter for that one setting:

   ```powershell
   gcloud run services update tilo-api --project essential-wares-510320-f0 --region asia-southeast1 `
     --update-env-vars "^@^TILO_API_CORS_ORIGINS=https://essential-wares-510320-f0.web.app,https://essential-wares-510320-f0.firebaseapp.com"
   ```

   Exact https origins only; one invalid entry and the API adds no CORS at all (no wildcard, no credentials).
4. `just deploy-dev-cloudbuild api` (the CORS code is in the image).
5. `$env:TILO_BAKE_FIREBASE_KEY="1"; just deploy-web-live`. It refuses to build without the Firebase config,
   bakes the fixed API origin (not a parameter) and deploys Hosting to the dev project only.
6. Open https://essential-wares-510320-f0.web.app and sign in with Google. This needs the Google provider enabled in
   Firebase Authentication and both Hosting domains in Auth, Settings, Authorized domains. Unverified: not checked
   by Tilo; if sign-in fails, look there first.

## App Check enforcement (SEC-10)

`tilo-api` checks the web client's `X-Firebase-AppCheck` token (`tilo_api.appcheck`) but enforcement stays off
until you flip it: with `TILO_APPCHECK_ENFORCE` unset a missing or refused token is only logged as a warning and
no answer changes. Turn it on only after the web app sends tokens in the deployed build and the log shows none
refused: set `TILO_APPCHECK_ENFORCE=1` on the Cloud Run service (only exactly `1` counts); unset it to turn it off.
`/health`, `/healthz` (probes carry no token) and the scheduler tick are never checked. The API reads the project from
`TILO_FIRESTORE_PROJECT` (else `GOOGLE_CLOUD_PROJECT`). Decisions: BQ-SEC10-1..5 in `docs/open-questions.md`.

### App Check in the web build (SEC-10)

The web client (the main app and the Park pages) sends `X-Firebase-AppCheck` on every API call
(`apps/web/src/appcheck/`), but only once the build has the Firebase web config: `VITE_FIREBASE_API_KEY` and
`VITE_FIREBASE_PROJECT_ID`. No key literal is in the repo.

**Owner step, before the first `just deploy-web` that bakes the key in.** The browser `apiKey` is written into the
public JavaScript bundle, and this project also uses Gemini Developer API keys, so the key is only harmless if it
is restricted. In the Google Cloud console (APIs and Services, Credentials) open the Firebase web key and
(a) set the API restriction to exactly three APIs: Firebase App Check API, Identity Toolkit API and Token Service API
(the last two are what Google sign-in calls; `infra/ACCESS.md` section 11); (b) set website restrictions to the referrers
`https://essential-wares-510320-f0.web.app/*` and `https://essential-wares-510320-f0.firebaseapp.com/*`;
(c) confirm it cannot call `generativelanguage.googleapis.com` or any other paid API. Then run
`TILO_BAKE_FIREBASE_KEY=1 just deploy-web` (in PowerShell: `$env:TILO_BAKE_FIREBASE_KEY = "1"` first).

`just deploy-web` without `TILO_BAKE_FIREBASE_KEY=1` builds with no Firebase config: App Check is skipped, the
browser console says so once, and nothing else changes. With it, `scripts/web_build_env.py` reads the output of
`firebase apps:sdkconfig WEB 1:379216745263:web:8cda5846cf882c2cefc7da --project essential-wares-510320-f0 --non-interactive --json`
into the build's environment (writes nothing to disk), and uses it only if the key has the Google key shape and the
project id is the dev project's; any `VITE_FIREBASE_*` already in your shell is dropped. If the command fails (you
are not signed in) the build goes ahead without the config. The two public ids (`FIREBASE_APP_ID`, the reCAPTCHA Enterprise site key) are recorded in
`infra/ACCESS.md` section 7, where enforcement is also recorded as OFF.

The deployed fixture world calls no API, so it never loads reCAPTCHA: App Check starts on the first API request.
Local hosts (localhost, 127.0.0.1) never start it.

Before you read the `tilo-api` log for refused or missing tokens, set `TILO_FIRESTORE_PROJECT` (or
`GOOGLE_CLOUD_PROJECT`) on the `tilo-api` Cloud Run service: with neither set the verifier has no project and
refuses every token, so the log would show every request as unverified.

## Durable stores (PROD-WIRE, ADR-0026; run this yourself, only after you accept ADR-0026)

tilo-api keeps its worlds, people and SEC-15 declarations in Firestore only when two runtime switches are set. They
are `gcloud` env, not Terraform (tilo-api has `ignore_env = true`), so no apply turns them on by itself:

1. Set `api_durable_stores = true` for the dev env and apply the Terraform plan: CPU stays allocated between
   requests on the one tilo-api instance (`max_instance_count = 1` holds either way; this raises idle cost).
2. Turn the stores on (`TILO_FIRESTORE_PROJECT` is already set by the routines rollout):

```powershell
gcloud run services update tilo-api --project essential-wares-510320-f0 --region asia-southeast1 `
  --update-env-vars "TILO_API_STORE=firestore,TILO_PEOPLE_STORE=firestore"
```

3. Check `/health`, that the instance count stays at 1, and run the tilo-api env audit in
   `docs/routines-rollout.md` ("Env drift check"). To switch back, `--remove-env-vars
   TILO_API_STORE,TILO_PEOPLE_STORE` (the doors answer 503 `not_configured` again), then set
   `api_durable_stores = false` and apply, so CPU is billed per request again.

### The SEC-16 spend-cap ledger (GOLIVE-935, issue 935; nothing for you to apply)

The live-model spend caps (`config/spend_caps.yaml`) are enforced on a Firestore ledger, `tilo_api.spend_firestore`:
documents `orgs/{org}/spend_ledger/{counter, hold, switch}`, each reserve, settle and release one transaction. It needs
only what is already there: `TILO_FIRESTORE_PROJECT` on `tilo-api` (set by the routines rollout) and the service
account's existing Firestore access (`roles/datastore.user`, as the schedule store). No composite index (single
document reads and writes only), no rules change (`firestore.rules` already denies every client path, and the server
bypasses them), no `TILO_API_STORE` and no always-on CPU (every call is inside a request). With no valid project or no
credentials the seam answers 503 and every request is replay, never uncapped. Reading it: `GET /access` says
`models: "live"` only while the ledger is readable, the uid is under its cap and the switch is off. To reset the
durable kill switch after the daily hard cap tripped it, delete the document `orgs/org_tilo/spend_ledger/switch`
(Firestore console) or set its `on` field to `false`; nothing in the API can.

### The Treasury credit ledger (T3, BQ-T3-1, BQ-MTR10-4; nothing for you to apply)

`GET /costs`, `GET /worlds/{id}/costs` (FR-MTR-10), `GET /v1/effort` and the web Ledger read, and Quick, the Meeting
Hall and the live metering write, one Firestore collection: `tilo_api.treasury_firestore`, documents
`orgs/{org}/treasury_ledger/{entry id}`, each written once (`create`), never updated or deleted. It needs only what is
already there, as the SEC-16 ledger above: `TILO_FIRESTORE_PROJECT` on `tilo-api` and the service account's existing
`roles/datastore.user`. No composite index (one equality query on `user`, served by Firestore's automatic single-field
index), no rules change (`firestore.rules` denies every client path), no `TILO_API_STORE`. With no valid project or no
credentials the routes answer 503 (`not_configured`, `store_unavailable`), never an empty report. Each live unit the
meter settles (GOLIVE-935) is also one entry here, written after the settle: a write that fails, or no writer wired,
logs one `treasury_ledger_write_failed` line at ERROR (the error type only; a log-based alert on that text is the
alert-able marker), is not retried, and never undoes the settled spend. The Ledger then under-reports that unit.

### Against a deployed tilo-api, and the smoke (PROD-WIRE-4)

```powershell
just deploy-web https://tilo-api-abc123def4-as.a.run.app     # your tilo-api url; the argument is positional
just smoke-dev https://tilo-api-abc123def4-as.a.run.app
```

`just deploy-web <api-url>` builds the web app with that url as `VITE_TILO_API_URL` (nothing else gets it; the
deploy line is unchanged and pinned to the dev project). With no argument the build is still the empty fixture
build, even if your shell has `VITE_TILO_API_URL` set. The url must be tilo-api's own Cloud Run service (the
Terraform module names it `tilo-api`) in lower case, no path, port or query:
`https://tilo-api-<hash>-as.a.run.app` or the deterministic
`https://tilo-api-<project-number>.asia-southeast1.run.app`. Another service name, a bare label or another region is
refused, so a typo or a pasted link never builds the app (or sends your token) to a stranger's service. `just`
checks it before any shell runs, on the first line of each recipe, which must stay first. `tilo-api` itself answers browser calls from the two hosting origins only
(`https://essential-wares-510320-f0.web.app` and `.firebaseapp.com`; BQ-PW-4); the CSP `connect-src` in
`firebase.json` is not widened yet (waits on CL-REACH's host list), so a deployed page cannot reach the API until
it is.

`just smoke-dev <api-url>` drives the deployed API the way a browser does and prints one line per step, stopping
at the first failure (exit 1):

| Step | What it proves |
| --- | --- |
| `health` | the service is up (`GET /health` is 200) |
| `cors-allowed` | a preflight from the hosting origin to a gated route is granted for that origin, no credentials |
| `cors-denied` | a preflight from any other origin gets no grant |
| `gate-closed` | a gated route with no token is refused (401 or 403): SEC-15 fails closed |
| `intake`, `answers`, `approaches`, `approve` | a signed-in person can start a task and approve an approach (replay mode, budget cap 50) |
| `gate-card`, `answer-card`, `delivery` | the run reaches its gate card, an in-app card is approved, and the completed run delivers |

The smoke approves nothing that leaves Tilo. It answers a gate card only when the card's tier is T1 or T2, it has no
recipient, and its action names no connector, item or destination; otherwise it stops with
`FAIL gate-card: not an in-app card; the smoke approves nothing that leaves Tilo` and sends no answer. Every gate card
names a connector today (card rule CR-10), so the signed-in steps end at `gate-card` on a real run: the guard
stays until adapters are wired (BQ-PW-4).

The first four need no sign-in. The rest run only when you set `TILO_SMOKE_ID_TOKEN` in your own shell to a Firebase
ID token you paste (for example `$env:TILO_SMOKE_ID_TOKEN = Read-Host`); otherwise the run ends with
`SKIP signed-in steps: set TILO_SMOKE_ID_TOKEN`. The token is sent only as `Authorization: Bearer ...` to the url
you gave (redirects are not followed), and is never printed, logged or written. It must be a JWT (three dot-separated
url-safe segments, no line break: a wrapped paste is refused with `FAIL token: TILO_SMOKE_ID_TOKEN is not a JWT`
before any request). A failure shows the HTTP status plus at most a short `detail` string from a JSON body (120
characters, withheld when it holds any run of the token), never a raw body; an exception shows its type name only.
Tilo never asks for or stores a password. The signed-in steps cannot pass on tilo-dev until the Firebase
ID-token verifier (`deps.get_current_principal`, CL-REACH) is wired; before that the API answers them 401 and the
smoke stops at `intake`. The smoke needs a real deployment and a person, so no workflow runs it and it is not part
of `just check` or `just test`.

## Never

- Never put a service-account key file in the repository or in Actions secrets: WIF only.
- Never deploy `tilo-demo` from this recipe, from `cloudbuild.yaml` or from the workflow.
- The only dispatch input is a fixed `service` choice, passed through `env:`, never into a script. Cloud Build's
  `_SERVICE` is passed the same way (a step environment variable, never spliced into the script, never `eval`ed).
- Cloud Build deploys no web app, no infrastructure and no IAM.
