# Tilo infrastructure (`infra/`)

Terraform for the `tilo-dev` environment (PRD 6.5). This plans infrastructure;
it never applies it. **You run `terraform apply` yourself** -- Claude Code's
tooling and hooks refuse to run `apply`, authenticate to Google Cloud, or
create projects.

Layout:

- `infra/modules/<name>/` -- reusable pieces: `service` (Cloud Run + its
  service account), `iam` (project IAM bindings), `storage` (buckets),
  `events` (Pub/Sub topic + BigQuery ledger), `kms` (key ring and keys),
  `wif` (GitHub OIDC + deployer service account), `budget` (billing budget).
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
  -out=tfplan

# 9. Apply -- YOU run this, never an agent.
terraform -chdir=infra/envs/dev apply tfplan
```

After apply, add the placeholder secrets' real values (workspace OAuth
client, WhatsApp API token, channels webhook signing key, email action-link
signing key) through the Cloud Console or `gcloud secrets versions add` --
Terraform declares the secrets but never writes a version (PRD 16.1 rule 4).

## Destroy

```powershell
terraform -chdir=infra/envs/dev destroy `
  -var="billing_account_id=YOUR_BILLING_ACCOUNT_ID" `
  -var="github_repository=owner/tilo" `
  -var="github_repository_id=REPO_ID" `
  -var="github_repository_owner_id=OWNER_ID"
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
