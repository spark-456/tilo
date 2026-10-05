# Acceptance tests for P0-07 / PRD-6.5 (Workload Identity Federation and billing budget).
# PRD 6.5 (CI/CD: WIF, no keys), 17.3 (cost ceilings).
#
# Run: terraform -chdir=infra/envs/dev test
#
# Expected root-module output contract (not yet implemented):
#
#   output "wif_pool_id" -> string
#   output "wif_provider_attribute_condition" -> string
#     The provider's attribute_condition expression; must reference
#     var.github_repository so only that repo's GitHub Actions runs can
#     authenticate.
#   output "deployer_service_account_email" -> string
#     The service account the WIF provider is allowed to impersonate.
#   output "billing_budget_amount_usd" -> number
#   output "billing_budget_threshold_percentages" -> list(number)
#     Alert thresholds as fractions, e.g. [0.5, 0.9, 1.0].

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

run "PRD_6_5_wif_provider_restricted_to_configured_repository" {
  command = plan

  assert {
    condition     = output.wif_pool_id != ""
    error_message = "A Workload Identity Federation pool must exist for GitHub Actions CI/CD (PRD 6.5)."
  }

  assert {
    condition     = strcontains(output.wif_provider_attribute_condition, var.github_repository)
    error_message = "The WIF provider's attribute condition must restrict to var.github_repository, so only that repo can authenticate (PRD 6.5, SEC-12 least privilege)."
  }
}

run "PRD_6_5_deployer_service_account_is_the_wif_impersonation_target" {
  command = plan

  assert {
    condition     = output.deployer_service_account_email != ""
    error_message = "A dedicated deployer service account must exist for the WIF provider to impersonate (PRD 6.5 CI/CD, no keys)."
  }
}

run "PRD_17_3_billing_budget_matches_ceiling_with_three_alerts" {
  command = plan

  assert {
    condition     = output.billing_budget_amount_usd == var.budget_amount_usd
    error_message = "The billing budget amount must track var.budget_amount_usd (PRD 17.3 cost ceilings)."
  }

  assert {
    condition     = toset(output.billing_budget_threshold_percentages) == toset([0.5, 0.9, 1.0])
    error_message = "The billing budget must alert at 50%, 90% and 100% (PRD 6.5/17.3 lean infrastructure and cost ceilings)."
  }
}

run "SEC_02_deployer_limited_to_main_and_runtime_service_accounts" {
  command = plan

  assert {
    condition     = strcontains(output.wif_provider_attribute_condition, "refs/heads/main")
    error_message = "The WIF provider must only accept tokens from main, not any branch (SEC-02, SEC-12)."
  }

  assert {
    condition     = !strcontains(output.wif_provider_attribute_condition, "refs/tags") && !strcontains(output.wif_provider_attribute_condition, "||")
    error_message = "The WIF provider must not accept tags or any alternative ref: tags bypass branch protection (SEC-02, SEC-12)."
  }

  assert {
    condition = alltrue([
      strcontains(output.wif_provider_attribute_condition, "assertion.repository_id == \"${var.github_repository_id}\""),
      strcontains(output.wif_provider_attribute_condition, "assertion.repository_owner_id == \"${var.github_repository_owner_id}\""),
    ])
    error_message = "The WIF provider must pin the immutable repository and owner ids as well as the name (SEC-02)."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : b.role != "roles/iam.serviceAccountUser"])
    error_message = "serviceAccountUser must be granted per service account, never project-wide (SEC-12)."
  }

  assert {
    condition     = length(output.deployer_act_as_service_accounts) == 7
    error_message = "The deployer may act as exactly the seven runtime service accounts (PRD 6.5)."
  }
}

run "SEC_02_deployer_cannot_change_cloud_run_iam" {
  command = plan

  assert {
    condition = alltrue([
      for b in output.project_iam_bindings :
      !(strcontains(b.member, "tilo-deployer@") && contains(["roles/run.admin", "roles/owner", "roles/editor"], b.role))
    ])
    error_message = "The WIF deployer must not hold run.admin, owner or editor: those can set allUsers run.invoker on internal services (PRD 6.5 ingress, SEC-02)."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : b.role != "roles/artifactregistry.writer"])
    error_message = "Artifact Registry write is scoped to the tilo repository, never project-wide (SEC-12)."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !strcontains(b.member, "tilo-deployer@")])
    error_message = "The WIF deployer holds no project-level role; run.developer is granted per service (SEC-12)."
  }

  assert {
    condition = alltrue([
      for s in values(output.cloud_run_services) :
      s.developers == ["serviceAccount:${output.deployer_service_account_email}"]
    ])
    error_message = "The deployer must hold run.developer on each of the seven services, and nobody else (PRD 6.5, SEC-12)."
  }
}
