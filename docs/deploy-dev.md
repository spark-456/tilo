# Deploy to tilo-dev (P0-07a)

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

## Web app (Firebase Hosting, manual)

```powershell
pnpm install
pnpm --filter @tilo/web run build     # writes apps/web/dist
pnpm exec firebase deploy --only hosting --project <project id>
```

`firebase.json` serves `apps/web/dist` with a single-page-app rewrite to `/index.html`. Sign in with
your own account (`firebase login`); Tilo's tooling never handles passwords.

## Never

- Never put a service-account key file in the repository or in Actions secrets: WIF only.
- Never deploy `tilo-demo` from this recipe or workflow.
- The only dispatch input is a fixed `service` choice, passed through `env:`, never into a script.
