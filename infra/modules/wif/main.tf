# Reusable piece: Workload Identity Federation for GitHub Actions CI/CD
# (PRD 6.5: "GitHub Actions with Workload Identity Federation"; PRD 16.1
# rule 5: "no keys in the repo"). The attribute condition restricts token
# exchange to var.github_repository (name, repository id and owner id) on
# refs/heads/main or refs/heads/phase0-stack (temporary, P0-07d: revert to
# main only once phase0-stack merges to main); the deployer service account
# is the only identity the provider may impersonate, and project roles for
# it are granted by the environment root through modules/iam.

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
    "google.subject"                = "assertion.sub"
    "attribute.repository"          = "assertion.repository"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }

  # Only tokens from this exact repository (name plus immutable numeric
  # repository and owner ids, so a renamed or recreated repo cannot match),
  # on refs/heads/main or refs/heads/phase0-stack only, may exchange for a
  # Google credential. The phase0-stack ref is temporary (P0-07d): the deploy
  # workflow must run from it until it merges to main, then remove it. No
  # wildcards and no tags: exact ref strings only. Tags are not accepted:
  # anyone with push access can tag an unreviewed commit,
  # bypassing branch protection, and the deployer can act as tilo-connectors
  # (PRD 6.5, SEC-02, SEC-12 least privilege).
  attribute_condition = join(" && ", [
    "assertion.repository == \"${var.github_repository}\"",
    "assertion.repository_id == \"${var.github_repository_id}\"",
    "assertion.repository_owner_id == \"${var.github_repository_owner_id}\"",
    "(assertion.ref == \"refs/heads/main\" || assertion.ref == \"refs/heads/phase0-stack\")",
  ])

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
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository_id/${var.github_repository_id}"
}
