# Reusable piece: Workload Identity Federation for GitHub Actions CI/CD
# (PRD 6.5: "GitHub Actions with Workload Identity Federation"; PRD 16.1
# rule 5: "no keys in the repo"). The attribute condition restricts token
# exchange to var.github_repository; the deployer service account is the
# only identity the provider may impersonate, and project roles for it are
# granted by the environment root through modules/iam.

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "tilo-github"
  display_name              = "Tilo GitHub Actions"
  description               = "Identities for GitHub Actions workflows in ${var.github_repository}."
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Only tokens asserting this exact repository may exchange for a Google
  # credential (PRD 6.5, SEC-12 least privilege).
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "tilo-deployer"
  display_name = "Tilo CI/CD deployer (WIF, no keys)"
}

resource "google_service_account_iam_member" "wif_impersonation" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}
