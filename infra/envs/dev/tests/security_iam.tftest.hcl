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

run "SEC_12_channels_cannot_write_firestore_or_publish_events" {
  command = plan

  assert {
    condition = alltrue([
      for b in output.project_iam_bindings :
      !(strcontains(b.member, "tilo-channels@") && contains(["roles/datastore.user", "roles/datastore.owner", "roles/firebase.admin", "roles/editor", "roles/owner", "roles/pubsub.publisher", "roles/pubsub.editor", "roles/pubsub.admin"], b.role))
    ])
    error_message = "tilo-channels writes only through the API: no Firestore write or Pub/Sub publish role (PRD 6.1, 15.3, SEC-12)."
  }
}

run "SEC_11_only_harness_publishes_to_tilo_events" {
  command = plan

  assert {
    condition     = output.events_topic_publishers == ["serviceAccount:tilo-harness@${var.project_id}.iam.gserviceaccount.com"]
    error_message = "Only tilo-harness may publish to tilo-events (PRD 15.3, SEC-11)."
  }

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : !contains(["roles/pubsub.publisher", "roles/pubsub.editor", "roles/pubsub.admin"], b.role)])
    error_message = "No project-wide Pub/Sub publish role: publish is granted on tilo-events only (SEC-12)."
  }
}

run "SEC_12_secrets_are_readable_only_by_their_owning_service" {
  command = plan

  assert {
    condition     = alltrue([for b in output.project_iam_bindings : b.role != "roles/secretmanager.secretAccessor"])
    error_message = "No project-wide secretAccessor; access is granted per secret (SEC-06, SEC-08, SEC-12)."
  }

  assert {
    condition = output.secret_accessors == {
      "workspace-oauth-client"       = ["serviceAccount:tilo-connectors@${var.project_id}.iam.gserviceaccount.com"]
      "whatsapp-api-token"           = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      "channels-webhook-signing-key" = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      # Changed by P0-07b: channels also signs and verifies action links (links.py), so it
      # needs read access as well as api. This is the only existing expectation edited.
      "email-action-link-signing-key" = ["serviceAccount:tilo-api@${var.project_id}.iam.gserviceaccount.com", "serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      # Added by the P0-07b access audit (additive; the four above are unchanged).
      "whatsapp-webhook-verify-token" = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      "channel-binding-hmac-key"      = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      "channel-number-encryption-key" = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      "webpush-vapid-private-key"     = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
    }
    error_message = "Each secret must be readable only by the service that owns it (SEC-12)."
  }
}
