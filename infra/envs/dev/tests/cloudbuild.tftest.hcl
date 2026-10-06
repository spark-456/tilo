# Acceptance tests for P0-07g: the dedicated Cloud Build service account used by PR #373 (cloudbuild.yaml,
# docs/deploy-dev.md "Deploy with Cloud Build"). Requirement id: P0-07g (PRD 6.3 Cloud Build, 6.5 least privilege,
# SEC-12; no PRD row of its own, the IAM list is the one in PR #373 and docs/deploy-dev.md).
#
#   terraform -chdir=infra/envs/dev test
#
# Output contract the builder must add to infra/envs/dev/outputs.tf (names and shapes are pinned here):
#
#   output "cloudbuild_service_account_email" -> string
#     "tilo-cloudbuild@<project>.iam.gserviceaccount.com".
#
#   output "cloudbuild_grants" -> list(object({ scope = string, resource = string, role = string }))
#     EVERY binding the Cloud Build identity holds, one entry each, derived from the real IAM resources:
#       scope "artifact_registry_repository" resource "tilo"                    role roles/artifactregistry.writer
#       scope "cloud_run_service"            resource "tilo-<svc>" (x7)         role roles/run.developer
#       scope "service_account"              resource "tilo-<svc>@<project>.iam.gserviceaccount.com" (x7)
#                                                                               role roles/iam.serviceAccountUser
#       scope "project"                      resource "<project id>"            role roles/logging.logWriter
#       scope "storage_bucket"               resource "<project>-cloudbuild-staging" role roles/storage.objectViewer
#     That is five roles and 17 bindings.
#
#   output "cloudbuild_act_as_service_accounts" -> list(string)
#     Same shape as deployer_act_as_service_accounts: "projects/<project>/serviceAccounts/tilo-<svc>@<project>..."
#     for the seven runtime service accounts the build may act as, and nothing else.
#
#   output "cloudbuild_staging_bucket" -> object({
#     name, location, uniform_bucket_level_access, public_access_prevention,
#     lifecycle_rules = list(object({ action_type = string, age_days = number })) })
#     A Terraform-managed source-staging bucket for `gcloud builds submit --gcs-source-staging-dir`. It is NOT
#     one of the keys of output.storage_buckets (that output keeps exactly artifacts, archive, snapshots, so
#     storage.tftest.hcl is untouched); the builder may reuse modules/storage a second time or write a resource.
#
# The run.developer grant must go through the existing module.service `developers` map (per service, same
# mechanism as the deployer), so it is also visible in output.cloud_run_services[*].developers.
#
# Ambiguities resolved here (the PR #373 text and PRD 6.5 give no more detail):
#   - Bucket name is "${project_id}-cloudbuild-staging" (modules/storage names buckets "${project_id}-<key>").
#   - Lifecycle: exactly one Delete rule at 7 days (the ticket's example; source tarballs are disposable).
#   - The build SA only READS the source (objectViewer). The submitting user writes it. With
#     options.logging CLOUD_LOGGING_ONLY the build writes no logs to any bucket, so no objectCreator/objectAdmin.

variables {
  project_id                 = "tilo-dev-test"
  region                     = "asia-southeast1"
  billing_account_id         = "000000-000000-000000"
  github_repository          = "tilo-org/tilo"
  github_repository_id       = "123456789"
  github_repository_owner_id = "987654321"
  budget_amount_usd          = 150
  alert_email                = "alerts@example.com"
}

mock_provider "google" {}
mock_provider "google-beta" {}

run "P0_07g_cloudbuild_service_account_exists_in_dev" {
  command = plan

  assert {
    condition     = output.cloudbuild_service_account_email == "tilo-cloudbuild@${var.project_id}.iam.gserviceaccount.com"
    error_message = "cloudbuild.yaml runs as tilo-cloudbuild@<project>; Terraform must create exactly that account."
  }
}

run "P0_07g_exactly_five_roles_and_seventeen_scoped_bindings" {
  command = plan

  assert {
    condition = toset(output.cloudbuild_grants[*].role) == toset([
      "roles/artifactregistry.writer",
      "roles/run.developer",
      "roles/iam.serviceAccountUser",
      "roles/logging.logWriter",
      "roles/storage.objectViewer",
    ])
    error_message = "tilo-cloudbuild holds exactly five roles (PR #373, docs/deploy-dev.md): AR writer, run.developer, serviceAccountUser, logWriter, objectViewer."
  }

  assert {
    condition = toset([for g in output.cloudbuild_grants : "${g.scope}|${g.resource}|${g.role}"]) == toset(concat(
      ["artifact_registry_repository|tilo|roles/artifactregistry.writer"],
      [for s in ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"] : "cloud_run_service|tilo-${s}|roles/run.developer"],
      [for s in ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"] : "service_account|tilo-${s}@${var.project_id}.iam.gserviceaccount.com|roles/iam.serviceAccountUser"],
      ["project|${var.project_id}|roles/logging.logWriter"],
      ["storage_bucket|${var.project_id}-cloudbuild-staging|roles/storage.objectViewer"],
    ))
    error_message = "The grant list must be exactly: AR writer on repository tilo; run.developer per service; serviceAccountUser per runtime SA; logWriter on the project; objectViewer on the staging bucket."
  }

  assert {
    condition     = length(output.cloudbuild_grants) == 17 && length(toset(output.cloudbuild_grants)) == 17
    error_message = "Five roles over 17 distinct bindings (1 + 7 + 7 + 1 + 1), no duplicates."
  }
}

run "P0_07g_artifact_registry_writer_on_repository_tilo_only" {
  command = plan

  assert {
    condition = [
      for g in output.cloudbuild_grants : g if g.role == "roles/artifactregistry.writer"
    ] == [{ scope = "artifact_registry_repository", resource = "tilo", role = "roles/artifactregistry.writer" }]
    error_message = "roles/artifactregistry.writer is granted on the repository tilo only (not project-wide, not another repository)."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !(strcontains(b.member, "tilo-cloudbuild@") && strcontains(b.role, "artifactregistry"))])
    error_message = "No project-wide Artifact Registry role for tilo-cloudbuild (SEC-12)."
  }
}

run "P0_07g_run_developer_per_service_through_developers_map_never_project_wide" {
  command = plan

  assert {
    condition = alltrue([
      for s in values(output.cloud_run_services) :
      contains(s.developers, "serviceAccount:tilo-cloudbuild@${var.project_id}.iam.gserviceaccount.com")
    ])
    error_message = "Each of the seven services lists tilo-cloudbuild in developers (module.service developers map, roles/run.developer)."
  }

  assert {
    condition     = length(output.cloud_run_services) == 7
    error_message = "Seven Cloud Run services (PRD 6.2); run.developer is granted on each of them."
  }

  assert {
    condition = alltrue([
      for b in output.project_iam_bindings :
      !(strcontains(b.member, "tilo-cloudbuild@") && startswith(b.role, "roles/run."))
    ])
    error_message = "No project-wide Cloud Run role (and never roles/run.admin) for tilo-cloudbuild."
  }

  assert {
    condition     = !contains(output.cloudbuild_grants[*].role, "roles/run.admin") && !contains(output.cloudbuild_grants[*].role, "roles/run.invoker")
    error_message = "tilo-cloudbuild never holds run.admin or run.invoker."
  }
}

run "P0_07g_service_account_user_on_each_runtime_sa_only" {
  command = plan

  assert {
    condition = toset(output.cloudbuild_act_as_service_accounts) == toset([
      for s in ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"] :
      "projects/${var.project_id}/serviceAccounts/tilo-${s}@${var.project_id}.iam.gserviceaccount.com"
    ])
    error_message = "tilo-cloudbuild may act as exactly the seven runtime service accounts (the updated revision runs as them)."
  }

  assert {
    condition     = length(output.cloudbuild_act_as_service_accounts) == 7
    error_message = "Seven act-as bindings, no duplicates."
  }

  assert {
    condition = alltrue([
      for a in output.cloudbuild_act_as_service_accounts :
      !strcontains(a, "tilo-tasks-invoker") && !strcontains(a, "tilo-gmail") && !strcontains(a, "tilo-deployer") && !strcontains(a, "tilo-cloudbuild")
    ])
    error_message = "No act-as on the Tasks, Gmail or deployer identities, and none on itself."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !(strcontains(b.member, "tilo-cloudbuild@") && b.role == "roles/iam.serviceAccountUser")])
    error_message = "serviceAccountUser is per service account, never project-wide (SEC-12)."
  }
}

run "P0_07g_project_level_binding_is_log_writer_only" {
  command = plan

  assert {
    condition = [
      for b in output.project_iam_bindings : b.role if strcontains(b.member, "tilo-cloudbuild@")
    ] == ["roles/logging.logWriter"]
    error_message = "The one project-level role tilo-cloudbuild holds is roles/logging.logWriter (CLOUD_LOGGING_ONLY), exactly once."
  }
}

run "P0_07g_staging_bucket_is_regional_private_and_short_lived" {
  command = plan

  assert {
    condition     = output.cloudbuild_staging_bucket.name == "${var.project_id}-cloudbuild-staging"
    error_message = "Staging bucket name is <project>-cloudbuild-staging (what --gcs-source-staging-dir and the docs reference)."
  }

  assert {
    condition     = output.cloudbuild_staging_bucket.location == "asia-southeast1"
    error_message = "The staging bucket lives in asia-southeast1, not the US multi-region gcloud would auto-create (CLAUDE.md region rule)."
  }

  assert {
    condition     = output.cloudbuild_staging_bucket.uniform_bucket_level_access == true
    error_message = "Uniform bucket-level access is on."
  }

  assert {
    condition     = output.cloudbuild_staging_bucket.public_access_prevention == "enforced"
    error_message = "Public access prevention is enforced (SEC-12)."
  }

  assert {
    condition     = output.cloudbuild_staging_bucket.lifecycle_rules == [{ action_type = "Delete", age_days = 7 }]
    error_message = "One lifecycle rule: delete objects after 7 days (uploaded source must not accumulate)."
  }

  assert {
    condition = length([
      for g in output.cloudbuild_grants : g if g.scope == "storage_bucket"
    ]) == 1 && length([for g in output.cloudbuild_grants : g if g.scope == "storage_bucket" && g.role == "roles/storage.objectViewer" && g.resource == output.cloudbuild_staging_bucket.name]) == 1
    error_message = "tilo-cloudbuild holds only objectViewer, on the staging bucket only (it reads the source; the submitting user writes it; CLOUD_LOGGING_ONLY writes no log object)."
  }

  assert {
    condition     = alltrue([for k in keys(output.service_storage_grants) : !strcontains(k, "cloudbuild")])
    error_message = "The runtime service accounts get nothing on the staging bucket (service_storage_grants has no cloudbuild key)."
  }

  assert {
    condition     = toset(keys(output.storage_buckets)) == toset(["artifacts", "archive", "snapshots"]) && !contains([for b in values(output.storage_buckets) : b.name], output.cloudbuild_staging_bucket.name)
    error_message = "storage_buckets keeps its three PRD buckets; the staging bucket is reported by cloudbuild_staging_bucket."
  }
}

run "P0_07g_no_broad_roles_no_keys_and_deployer_unchanged" {
  command = plan

  assert {
    condition = alltrue([
      for g in output.cloudbuild_grants : !contains([
        "roles/owner", "roles/editor", "roles/viewer",
        "roles/iam.serviceAccountTokenCreator", "roles/iam.serviceAccountAdmin", "roles/iam.serviceAccountKeyAdmin",
        "roles/run.admin", "roles/storage.admin", "roles/storage.objectAdmin", "roles/storage.objectUser",
        "roles/artifactregistry.admin", "roles/cloudbuild.builds.builder", "roles/cloudbuild.builds.editor",
        "roles/resourcemanager.projectIamAdmin", "roles/secretmanager.secretAccessor", "roles/datastore.user",
        "roles/cloudkms.cryptoKeyEncrypterDecrypter", "roles/cloudkms.cryptoKeyDecrypter",
      ], g.role)
    ])
    error_message = "tilo-cloudbuild holds none of: owner, editor, token creator, key admin, run.admin, storage admin/objectAdmin, AR admin, builder roles, KMS, Firestore, Secret Manager."
  }

  assert {
    condition     = output.service_account_key_count == 0
    error_message = "No google_service_account_key anywhere under infra/ (PRD 16.1 rule 5): the build identity has no key."
  }

  assert {
    condition     = output.cloudbuild_service_account_email != output.deployer_service_account_email
    error_message = "tilo-cloudbuild is its own identity, not the WIF deployer."
  }

  assert {
    condition     = length(output.deployer_act_as_service_accounts) == 7 && length(var.deployer_project_roles) == 0
    error_message = "The deployer's grants are unchanged: seven act-as bindings, no project role."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !strcontains(b.member, "tilo-deployer@")])
    error_message = "Adding tilo-cloudbuild must not give the deployer a project-level role."
  }
}
