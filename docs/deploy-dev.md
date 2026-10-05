# Deploy to tilo-dev (P0-07a, P0-07c)

## User's one sitting (about 10 min)

Copy and paste in this order, from the repository root, signed in to `gh` as yourself. Tilo's tooling
runs none of these.

1. Web app on Firebase Hosting (opens a browser for your own Google sign-in):

   ```powershell
   pnpm install
   pnpm exec firebase login
   just deploy-web
   ```

   Result: https://essential-wares-510320-f0.web.app (the default Hosting site).

2. The three repository variables (variables, not secrets; no key file anywhere):

   ```powershell
   gh variable set GCP_PROJECT_ID --repo spark-456/tilo --body essential-wares-510320-f0
   gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo spark-456/tilo --body projects/379216745263/locations/global/workloadIdentityPools/tilo-github/providers/github
   gh variable set GCP_DEPLOYER_SERVICE_ACCOUNT --repo spark-456/tilo --body tilo-deployer@essential-wares-510320-f0.iam.gserviceaccount.com
   ```

3. Get the deploy workflow onto `main` (the WIF provider trusts only `refs/heads/main`). Either:
   - merge PR #356 (fast-forwards `main` to `phase0-stack`), or
   - apply PR #353 (the WIF provider also trusts `phase0-stack`; you apply it per `infra/README.md`).

4. Deploy the services, API first, check it, then everything:

   ```powershell
   gh workflow run deploy-dev.yml --ref main -f service=api
   gh run watch
   gh workflow run deploy-dev.yml --ref main -f service=all
   ```

5. What to expect: `tilo-api` fails closed without a principal (a request with no sign-in is refused;
   that is correct, not a bug). Cloud Run may reserve `/healthz`, so the smoke step can fail after traffic
   has already moved to the new revision; if so, see issue #355 (the service is up, the check is wrong).

The web app and the services are independent: step 1 needs no workflow, no `main` and no repository
variables.

How the seven Cloud Run services and the web app reach `tilo-dev`. Region `asia-southeast1`. This
runbook is for `tilo-dev` only: nothing here ever targets `tilo-demo` (that deploy is a separate,
user-approved step, never from this workflow or recipe).

## What deploys what

| Piece | How | Where it is defined |
| --- | --- | --- |
| Services `tilo-api`, `tilo-harness`, `tilo-channels`, `tilo-connectors`, `tilo-browser`, `tilo-render`, `tilo-sandbox-web` | `.github/workflows/deploy-dev.yml` (`workflow_dispatch` only), built from `services/<svc>/Dockerfile` with the repo root as context | PRD 6.2, 6.5 |
| Web app (`apps/web`) | Firebase Hosting, by hand (below). The CI deployer has no Firebase role by design | `firebase.json` |
| Infrastructure (services, IAM, ingress, env, secrets) | Terraform, applied by you (`infra/README.md`) | `infra/` |

The workflow only swaps the image (pinned by digest) and passes `--min-instances 0` and
`--max-instances 2..3` on an existing service. It never sets ingress, IAM, env vars or secrets;
Terraform owns those and ignores image changes (`infra/modules/service`).

## One-time setup (you do this once, after `terraform apply`)

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

## Deploy

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
- `firebase.json` serves `apps/web/dist` with a single-page-app rewrite to `/index.html`, hashed files
  under `/assets/**` as `public, max-age=31536000, immutable`, and `index.html` as `no-cache` so a new
  deploy is picked up on the next load. Every route also gets `Content-Security-Policy` (self only,
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
- Never deploy `tilo-demo` from this recipe or workflow.
- The only dispatch input is a fixed `service` choice, passed through `env:`, never into a script.
