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

| Piece | How | Where it is defined |
| --- | --- | --- |
| Services `tilo-api`, `tilo-harness`, `tilo-channels`, `tilo-connectors`, `tilo-browser`, `tilo-render`, `tilo-sandbox-web` | Google Cloud Build: `just deploy-dev-cloudbuild` runs `cloudbuild.yaml` (P0-07f). Alternative: `.github/workflows/deploy-dev.yml` (`workflow_dispatch` only). Both build `services/<svc>/Dockerfile` with the repo root as context | PRD 6.2, 6.5 |
| Web app (`apps/web`) | Firebase Hosting, by hand (below). The CI deployer has no Firebase role by design | `firebase.json` |
| Infrastructure (services, IAM, ingress, env, secrets) | Terraform, applied by you (`infra/README.md`) | `infra/` |

Cloud Build and the workflow only swap the image (pinned by digest) and passes `--min-instances 0` and
`--max-instances 2..3` on an existing service. It never sets ingress, IAM, env vars or secrets;
Terraform owns those and ignores image changes (`infra/modules/service`).

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
`gcloud run services update tilo-<svc> --image <repo>@sha256:<digest> --min-instances 0 --max-instances 2..3`,
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

## Web app (Firebase Hosting, manual; P0-07c)

```powershell
pnpm install
pnpm exec firebase login      # once: you sign in with your own Google account (browser)
just deploy-web
```

`just deploy-web` builds `apps/web` with `VITE_TILO_API_URL` set to empty, then runs
`pnpm exec firebase deploy --only hosting --project essential-wares-510320-f0`. It takes no argument
and refuses every other project by construction (the project id is fixed in the recipe). The
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
  `connect-src 'self'`, `frame-ancestors 'none'`, no `unsafe-eval`: the web app loads
  `pixi.js/unsafe-eval`), `X-Content-Type-Options: nosniff` and
  `Referrer-Policy: strict-origin-when-cross-origin`. A new backend origin for the web app must be
  added to `connect-src` when the app is pointed at a deployed `tilo-api`.
- Two Hosting sites exist in the project: the default site `essential-wares-510320-f0`
  (https://essential-wares-510320-f0.web.app, the one this deploy targets, so `firebase.json` has no
  `site` key) and the Terraform-created `essential-wares-510320-f0-web`
  (https://essential-wares-510320-f0-web.web.app). The `-web` site is optional and unused.
- Check before you deploy: `pnpm --filter @tilo/web run build` then `pnpm --filter @tilo/web exec vite preview`
  serves the same bundle locally.

## Never

- Never put a service-account key file in the repository or in Actions secrets: WIF only.
- Never deploy `tilo-demo` from this recipe, from `cloudbuild.yaml` or from the workflow.
- The only dispatch input is a fixed `service` choice, passed through `env:`, never into a script. Cloud Build's
  `_SERVICE` is passed the same way (a step environment variable, never spliced into the script, never `eval`ed).
- Cloud Build deploys no web app, no infrastructure and no IAM.
