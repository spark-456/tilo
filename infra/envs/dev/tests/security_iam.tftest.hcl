# Acceptance tests for P0-07 / PRD-6.5 (identity and key policy, PRD 6.5, 16.1, 16.4).
#
# Run: terraform -chdir=infra/envs/dev test
#
# Expected root-module output contract (not yet implemented):
#
#   output "oauth_token_key_decrypters" -> list(string)
#     Member emails/principals granted roles/cloudkms.cryptoKeyDecrypter on
#     the oauth-tokens KMS key. Must contain only the connectors SA.
#
#   output "browser_service_account_project_roles" -> list(string)
#     Project-level IAM roles bound to the tilo-browser service account.
#     Must not include any Firestore/Datastore or Storage role.
#
#   output "service_account_key_count" -> number
#     Count of google_service_account_key resources anywhere in the plan.
#     Must be 0 (PRD 16.1 rule 5: no keys in the repo; WIF only).
#
#   output "secret_manager_secret_version_count" -> number
#     Count of google_secret_manager_secret_version resources in the plan.
#     Must be 0: secrets are declared as placeholders, values added by the
#     user out of band, never in code (PRD 16.1 rule 4).

variables {
  project_id         = "tilo-dev-test"
  region             = "asia-southeast1"
  billing_account_id = "000000-000000-000000"
  github_repository  = "tilo-org/tilo"
  budget_amount_usd  = 150
}

mock_provider "google" {}
mock_provider "google-beta" {}

run "SEC_02_only_connectors_sa_can_decrypt_oauth_tokens" {
  command = plan

  assert {
    condition     = length(output.oauth_token_key_decrypters) == 1
    error_message = "Exactly one principal may decrypt the oauth-tokens KMS key (SEC-02)."
  }

  assert {
    condition     = strcontains(output.oauth_token_key_decrypters[0], "connectors")
    error_message = "Only the tilo-connectors service account may decrypt OAuth tokens (PRD 6.5, SEC-02)."
  }
}

run "SEC_12_browser_sa_cannot_read_firestore_or_storage" {
  command = plan

  assert {
    condition = alltrue([
      for role in output.browser_service_account_project_roles :
      !strcontains(role, "datastore") && !strcontains(role, "firestore") && !strcontains(role, "storage")
    ])
    error_message = "tilo-browser must not hold any Firestore or Cloud Storage role (PRD 6.5: tilo-browser cannot read Firestore or storage)."
  }
}

run "SEC_16_1_no_service_account_keys_anywhere" {
  command = plan

  assert {
    condition     = output.service_account_key_count == 0
    error_message = "No google_service_account_key resource may exist anywhere in the plan (PRD 16.1 rule 5)."
  }
}

run "SEC_16_1_secrets_are_placeholders_with_no_versions" {
  command = plan

  assert {
    condition     = output.secret_manager_secret_version_count == 0
    error_message = "Secret Manager secrets are declared but no versions are created in Terraform; values come from the user (PRD 16.1 rule 4)."
  }
}
