# infra/ -- Tilo infrastructure

Purpose: Terraform for `tilo-dev` (PRD 6.5). Plans and documents commands
only; the user applies.

## Commands

```powershell
terraform fmt -check -recursive infra
terraform -chdir=infra/envs/dev init -backend=false
terraform -chdir=infra/envs/dev validate
terraform -chdir=infra/envs/dev test
```

Full apply flow (with credentials): see `infra/README.md`.

## Rules

- Never run `terraform apply`, never authenticate to Google Cloud, never
  create a project or touch billing. `.claude/hooks/guard.py` blocks
  `terraform apply` anyway -- do not work around it.
- Region `asia-southeast1`; one least-privilege service account per Cloud
  Run service (PRD 6.5); no `google_service_account_key` resource anywhere.
- Secrets are declared in Secret Manager as placeholders only -- never add a
  `google_secret_manager_secret_version` in code (PRD 16.1 rule 4).
- Only `tilo-connectors` may decrypt the `oauth-tokens` KMS key (SEC-02);
  `tilo-browser` holds no Firestore/Datastore or Storage IAM role (SEC-12).
- CI/CD authenticates through Workload Identity Federation
  (`infra/modules/wif`), restricted to `var.github_repository` (name,
  repository id and owner id) on `refs/heads/main` only, never tags. No
  keys. Grant roles per resource (topic, secret, key, bucket, service),
  never project-wide, and keep `run.invoker` scoped to real callers.
- Keep `infra/modules/*` reusable and DRY: a new Cloud Run service is a new
  entry in the `cloud_run_services` map in `infra/envs/dev/main.tf`, not a
  copy-pasted resource block.
- The acceptance tests in `infra/envs/dev/tests/*.tftest.hcl` define the
  root module's output contract (names, shapes). Keep outputs in sync;
  never weaken an assertion to make a test pass.
