# Tilo infrastructure (`infra/`)

Terraform for the `tilo-dev` environment (PRD 6.5). This plans infrastructure;
it never applies it. **You run `terraform apply` yourself** -- Claude Code's
tooling and hooks refuse to run `apply`, authenticate to Google Cloud, or
create projects.

Layout:

- `infra/modules/<name>/` -- reusable pieces: `service` (Cloud Run + its
  service account), `iam` (project IAM bindings), `storage` (buckets),
  `events` (Pub/Sub topic + BigQuery ledger), `kms` (key ring and keys),
  `wif` (GitHub OIDC + deployer service account), `budget` (billing budget), `monitoring` (email channel and SLO alert policies).
- `infra/envs/dev/` -- composes the modules into the `tilo-dev` environment.

## Commands (Windows PowerShell)

Run these in order from the repo root. Each one waits for the previous to
finish; read the output before moving on.

```powershell
# 1. Sign in (interactive browser login; used for gcloud CLI calls below).
gcloud auth login

# 2. Let Terraform's google/google-beta providers use your user credentials.
gcloud auth application-default login

# 3. Create the tilo-dev project, or choose an existing one you own.
#    GCP project ids are globally unique -- if "tilo-dev" is taken, pick
#    another id and pass it as project_id in later steps.
gcloud projects create tilo-dev --name="Tilo dev"
gcloud config set project tilo-dev
#    Make the project the quota project for your application-default
#    credentials. The billing-budget and Firebase APIs reject user
#    credentials without one (providers.tf also sets billing_project).
gcloud auth application-default set-quota-project tilo-dev

# 4. Link a billing account (required before any API can be enabled).
gcloud billing accounts list
gcloud billing projects link tilo-dev --billing-account=YOUR_BILLING_ACCOUNT_ID
#    Enable the two APIs Terraform needs before it can enable the rest.
#    The plan reads the project (Cloud Resource Manager) and enables APIs
#    (Service Usage), and every request is quota-checked against tilo-dev
#    (step 3). A new project does not have Cloud Resource Manager enabled,
#    so without this the first plan fails with 403 SERVICE_DISABLED.
gcloud services enable cloudresourcemanager.googleapis.com serviceusage.googleapis.com --project=tilo-dev

# 5. Create the Terraform state bucket (name must be globally unique).
gcloud storage buckets create gs://tilo-dev-tfstate `
  --project=tilo-dev --location=asia-southeast1 `
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://tilo-dev-tfstate --versioning

# 6. Point Terraform at that bucket.
Copy-Item infra/envs/dev/backend.hcl.example infra/envs/dev/backend.hcl
# then edit infra/envs/dev/backend.hcl: set bucket = "tilo-dev-tfstate"

# 7. Initialise, using the backend config from step 6.
terraform -chdir=infra/envs/dev init -backend-config=backend.hcl

# 8. Plan. Supply the variables that have no default. The WIF provider
#    pins the GitHub repository's numeric id and owner id as well as its
#    name, and accepts tokens from refs/heads/main only (no tags). Look the
#    ids up with the GitHub CLI (or the repo's API page):
gh api repos/owner/tilo --jq '.id, .owner.id'
terraform -chdir=infra/envs/dev plan `
  -var="billing_account_id=YOUR_BILLING_ACCOUNT_ID" `
  -var="github_repository=owner/tilo" `
  -var="github_repository_id=REPO_ID" `
  -var="github_repository_owner_id=OWNER_ID" `
  -var="alert_email=you@example.com" `
  -out=tfplan

# 9. Apply -- YOU run this, never an agent.
terraform -chdir=infra/envs/dev apply tfplan
```

After apply, add the placeholder secrets' real values (workspace OAuth
client, WhatsApp API token, channels webhook signing key, email action-link
signing key) through the Cloud Console or `gcloud secrets versions add` --
Terraform declares the secrets but never writes a version (PRD 16.1 rule 4).

`alert_email` has no default; it receives the Cloud Monitoring alerts.
Optional thresholds live in `infra/modules/monitoring/variables.tf`
(defaults: 5xx ratio 2% per NFR-23, request latency p95 25000 ms, events
backlog 600 s, each held 300 s). Alerts are metric-based, so nothing keeps a
scale-to-zero service warm.

Owner cost alerts (NFR-27): `tilo_metering.CostAlerts` writes one redacted JSON
line per alert to stdout (`"event": "cost_alert"`, kind `uid_cap_80`,
`uid_cap_100` or `global_daily`; the uid appears only as the `uid_ref` digest).
The monitoring module's log-based metric `tilo_cost_alert` counts those lines
and the "Tilo owner cost alert" policy emails `alert_email`, at most once an
hour. It is alert-only: spend is never blocked. This change is Terraform in a
PR; it takes effect when you run the apply step above. The uid cap and daily
USD threshold are constructor arguments until the caps move into
`config/metering.yaml` (BQ-276); the lines carry the figures.

The access audit (`infra/ACCESS.md`) lists every API, IAM grant, secret slot,
OAuth scope and console step; read its section 7 and 8 before applying.
It adds the `gmail_push` module, a Model Armor template, bucket-scoped
service grants and the optional `deployer_project_roles` (left empty for dev)
and `model_armor_location` variables. The oauth-tokens key binding changes
role (connectors may now encrypt too), which Terraform shows as one replace.
Expect about 55 to add, 0 to change, 2 to destroy in total from the P0-07
state (17 APIs, 4 monitoring, 9 secret slots and accessors, 7 storage
grants, 5 project grants plus 1 custom Vertex role, 6 Gmail push, 2 service
accounts, 1 Model Armor template, 2 invokers, 1 KMS replace). The 2 destroys
are the old KMS decrypter binding and api's accessor on
`email-action-link-signing-key` (moved to channels). Firebase deploys are manual: see
`infra/ACCESS.md` section 7.

### What apply will change (P0-07b, on top of an already-applied P0-07)

Expect **14 to add, 0 to change, 0 to destroy**: ten `google_project_service`
entries (modelarmor, cloudscheduler, identitytoolkit, firebaseappcheck,
monitoring, cloudtrace, logging, plus gmail, calendar-json and drive, which
you enabled by hand: enabling an enabled API is a no-op), one email
notification channel and three alert policies. The Cloud Run services no
longer show an in-place diff for the API-defaulted service-level `scaling`
block, and the `secret_accessors` output is the same before and after a refresh.

### What apply will add for scheduled runs (FR-AGT-14, on top of the above)

Expect **3 to add, 0 to change, 0 to destroy**: the service account
`tilo-schedule-scheduler` (no IAM binding at all), one Cloud Scheduler job,
`tilo-schedule-tick` (every minute, UTC, OIDC, `retry_count` 1), which POSTs
`/internal/schedules/tick` on tilo-api, and the Firestore composite index
`schedules` (`enabled`, `next_due`) that the due query needs. The route answers
503 until you set `TILO_SCHEDULE_TICK_AUDIENCE`, `TILO_SCHEDULE_TICK_CALLER`
(`tilo-schedule-scheduler@<project>.iam.gserviceaccount.com`),
`TILO_SCHEDULES_STORE=firestore` and `TILO_FIRESTORE_PROJECT` on tilo-api (ADR-0023) AND
production wires the api store and run seams (`deps.get_store`, the artifact store,
redactor and run archive: today they answer 503 when deployed), so setting the variables
alone does not make the tick work; until then the job fires into a 503. Copy the audience
from `terraform output schedule_tick` (the `audience` field) instead of retyping the api
URL: Cloud Run has two URL forms and a mismatch is a silent 401. Deploy the rules BEFORE
setting `TILO_SCHEDULES_STORE=firestore`:
`pnpm exec firebase deploy --only firestore:rules --project <project>`; they deny every
client the `schedules` collection. Terraform only: the user applies it.

### Cloud Tasks hand-off for scheduled runs (FR-AGT-14e)

No Terraform change: the tick no longer starts the run on the Scheduler's request (Cloud Run
bills request-based CPU, so a run thread there is throttled and lost on scale-to-zero). It
hands each due slot to the existing Cloud Tasks queue `runs`, and Cloud Tasks delivers it to
the same tick route as `tilo-tasks-invoker`, where the run executes inside that request.
`tilo-api` (and `tilo-harness`) already hold `roles/cloudtasks.enqueuer` and `serviceAccountUser` on
`tilo-tasks-invoker`, and api is public, so a task reaches it without any `run.invoker`.
Two more variables on tilo-api are yours to set (the tick answers 503 until both are set):

- `TILO_TASKS_CALLER` = `tilo-tasks-invoker@<project>.iam.gserviceaccount.com`
- `TILO_RUNS_QUEUE` = `projects/<project>/locations/asia-southeast1/queues/runs`

They must differ from `TILO_SCHEDULE_TICK_CALLER`: the Scheduler never gets the task mode
and Cloud Tasks never gets the fan-out (one account for both is refused). One setting is
not in Terraform yet: the request timeout of `tilo-api` is Cloud Run's 300 s default, and
a delivery waits up to 1500 s for its run, so set it to 1800 s,
`gcloud run services update tilo-api --timeout=1800 --region asia-southeast1`, until an
infra ticket adds `timeout` to the service module (open in BQ-AGT14-5).

## Destroy

```powershell
terraform -chdir=infra/envs/dev destroy `
  -var="billing_account_id=YOUR_BILLING_ACCOUNT_ID" `
  -var="github_repository=owner/tilo" `
  -var="github_repository_id=REPO_ID" `
  -var="github_repository_owner_id=OWNER_ID" `
  -var="alert_email=you@example.com"
```

The `oauth-tokens` and `archive` KMS keys have `prevent_destroy`; remove that
lifecycle block first if you really mean to destroy the environment.

The buckets have `force_destroy = false`, so destroy fails on any bucket that
still holds objects (including old versions in `artifacts`). Empty them first,
for example `gcloud storage rm --recursive --all-versions "gs://BUCKET_NAME/**"` for each
bucket named in `terraform -chdir=infra/envs/dev output`, then rerun destroy.

## Checks (no credentials, no network calls to GCP)

```powershell
terraform fmt -check -recursive infra
terraform -chdir=infra/envs/dev init -backend=false
terraform -chdir=infra/envs/dev validate
terraform -chdir=infra/envs/dev test
```
