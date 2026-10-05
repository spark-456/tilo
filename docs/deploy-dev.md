# Deploy to tilo-dev (P0-07a, P0-07c)

## User's one sitting (about 10 min)

Copy and paste in this order, from the repository root. Services deploy with Google Cloud Build (P0-07f), so
no GitHub variable, no merge to `main` and no `gh` sign-in is needed. Tilo's tooling runs none of these.

1. Sign in to Google Cloud as yourself (opens a browser) and point `gcloud` at the tilo-dev project:

   ```powershell
   gcloud auth login
   gcloud config set project essential-wares-510320-f0
   ```

   Use the Google account that owns the project. If `gcloud` is not installed, install the Google Cloud CLI first.

2. Web app on Firebase Hosting (opens a browser for your own Google sign-in; use the account that has Firebase
   access on project `essential-wares-510320-f0`, any other account fails with a permission error):

   ```powershell
   pnpm install
   pnpm exec firebase login
   just deploy-web
   ```

   Result: https://essential-wares-510320-f0.web.app (the default Hosting site).

3. One-time, before the first service deploy: apply the separate Terraform PR that gives the Cloud Build service
   account its access (see "Deploy with Cloud Build" below). Until it is applied the build fails closed with a
   permission error and changes nothing.

4. Deploy the services, API first, check it, then everything:

   ```powershell
   just deploy-dev-cloudbuild api
   just deploy-dev-cloudbuild all
   ```

   Each call uploads the repo (`.gcloudignore` keeps secrets and VCS data out), builds in `asia-southeast1`
   and prints the build log. The seven services are `api`, `harness`, `channels`, `connectors`, `browser`,
   `render`, `sandbox-web`.

5. What to expect: `tilo-api` fails closed without a principal (a request with no sign-in is refused;
   that is correct, not a bug). Cloud Build does not smoke test: look at the services in the Cloud Run console, or
   run `gcloud run services describe tilo-api --region asia-southeast1` and check the Ready condition.

The web app and the services are independent: step 2 needs no build, and the services need no Hosting deploy.

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
condition. Services with public ingress (api, channels, sandbox-web) also get `curl --fail` on `/healthz`.
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
`gcloud builds submit --config cloudbuild.yaml --substitutions _SERVICE=<service> --region asia-southeast1 .`.
`cloudbuild.yaml` (repo root) has three steps: check `_SERVICE` (`all` or one of the seven short names, anything
else fails with `unknown service`), build each image from `services/<svc>/Dockerfile` with the repo root as
context and push it to `asia-southeast1-docker.pkg.dev/<project>/tilo/<svc>:<build id>`, then
`gcloud run services update tilo-<svc> --image <repo>@sha256:<digest> --min-instances 0 --max-instances 2..3`.
The project id is Cloud Build's `$PROJECT_ID`, never written in the file. Nothing else is touched: no ingress, IAM,
env vars, secrets or service account flag. The build times out at 2700 s (the 45 minute cap of the workflow), logs
go to Cloud Logging only, and the builder images are pinned and listed in `docs/licences.md`.

Rollback: send traffic to a previous revision in the Cloud Run console, or revert and run the recipe again.

### IAM the Cloud Build service account needs (a separate Terraform PR, put in place by you)

The build runs as the project's Cloud Build service account (check which one with
`gcloud builds get-default-service-account --region asia-southeast1`; a project created in 2024 or later uses the
Compute Engine default account). It needs exactly this, scoped the way the deployer's access is, and no key:

- `roles/artifactregistry.writer` on the Artifact Registry repository `tilo` (not project-wide).
- `roles/run.developer` on each of the seven services `tilo-<svc>` (per service, never project-wide, and never
  `roles/run.admin`). `run.developer` cannot set IAM, so invoker bindings stay with Terraform.
- `roles/iam.serviceAccountUser` on each of the seven runtime service accounts (the updated revision runs as them).
- `roles/logging.logWriter` at project level (Google offers no narrower scope), so `CLOUD_LOGGING_ONLY` works.
- `roles/storage.objectViewer` on the source staging bucket `<project>_cloudbuild`, so the build can read the upload.

The exact list is in the description of the separate Terraform PR; Tilo's tooling writes it and you run it
(`infra/README.md`). Until it is in place, `just deploy-dev-cloudbuild` fails with a permission error and changes
nothing. You, as the person running `gcloud builds submit`, need `roles/cloudbuild.builds.editor` and permission to
act as the build account (the project owner has both).

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
