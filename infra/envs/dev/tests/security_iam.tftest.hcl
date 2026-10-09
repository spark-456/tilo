# Acceptance tests for P0-07 / PRD-6.5 (identity and key policy, PRD 6.5, 16.1, 16.4).
#
# Run: terraform -chdir=infra/envs/dev test
#
# Expected root-module output contract (not yet implemented):
#
#   output "oauth_token_key_decrypters" -> list(string)
#     Member emails/principals granted roles/cloudkms.cryptoKeyEncrypterDecrypter on
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
      # Changed by P0-07b: channels issues and verifies action links (links.py) and no api
      # code uses the key, so channels is the only accessor (was api). The only existing
      # secret expectation edited; the four secrets pinned originally are otherwise unchanged.
      "email-action-link-signing-key" = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      # Added by the P0-07b access audit (additive; the four above are unchanged).
      "whatsapp-webhook-verify-token" = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      "channel-binding-hmac-key"      = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      "channel-number-encryption-key" = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
      "webpush-vapid-private-key"     = ["serviceAccount:tilo-channels@${var.project_id}.iam.gserviceaccount.com"]
    }
    error_message = "Each secret must be readable only by the service that owns it (SEC-12)."
  }
}

# ADR-0032 decision 9 (T5): tokens live in their own Firestore database. A Firestore IAM condition can name a
# database (resource.name) but not a collection or document path, so a project-wide datastore.user on api, harness or
# render would reach connector_tokens in the default database. The tokens database is `tilo-tokens`; only the
# connectors service account may use it; every other datastore.user binding is limited to the default database.
run "SEC_02_only_connectors_can_reach_the_token_database" {
  command = plan

  assert {
    condition     = output.token_database.name == "tilo-tokens" && output.token_database.type == "FIRESTORE_NATIVE" && output.token_database.location_id == var.region
    error_message = "A native Firestore database `tilo-tokens` in var.region holds the connector token records."
  }

  # A binding reaches tilo-tokens when it has no condition, or a condition that does not pin the default database.
  assert {
    condition = toset([
      for b in output.project_iam_bindings : b.member
      if startswith(b.role, "roles/datastore.") && (b.condition == null || !strcontains(coalesce(b.condition, ""), "databases/(default)"))
    ]) == toset(["serviceAccount:tilo-connectors@${var.project_id}.iam.gserviceaccount.com"])
    error_message = "Only tilo-connectors may reach the token database; api, harness and render datastore.user is limited to the (default) database by an IAM condition."
  }

  # The condition is pinned by exact equality (a substring check passed `|| true`, `!=` and an appended startsWith).
  assert {
    condition = alltrue([
      for b in output.project_iam_bindings : b.condition == "resource.name == \"projects/${var.project_id}/databases/(default)\""
      if startswith(b.role, "roles/datastore.") && !strcontains(b.member, "tilo-connectors@")
    ])
    error_message = "Every datastore binding except connectors' must carry exactly the (default)-database condition."
  }

  # api, harness and render hold no broad or custom role that could reach tilo-tokens another way.
  assert {
    condition = alltrue([
      for b in output.project_iam_bindings : !contains([
        "roles/owner", "roles/editor", "roles/viewer", "roles/firebase.admin", "roles/firebase.developAdmin",
        "roles/datastore.owner", "roles/datastore.viewer", "roles/datastore.importExportAdmin",
      ], b.role) && (!startswith(b.role, "projects/") || b.role == "projects/${var.project_id}/roles/tiloVertexGenerate")
      if length([for n in ["api", "harness", "render"] : n if strcontains(b.member, "tilo-${n}@")]) > 0
    ])
    error_message = "api, harness and render hold no owner, editor, viewer, firebase.admin, other datastore role or custom role beyond tiloVertexGenerate."
  }

  assert {
    condition = alltrue([
      for name in ["api", "harness", "render"] :
      length([for b in output.project_iam_bindings : b if b.role == "roles/datastore.user" && strcontains(b.member, "tilo-${name}@") && b.condition != null]) == 1
    ])
    error_message = "api, harness and render each keep exactly one datastore.user binding, with the (default) database condition."
  }

  assert {
    condition     = length([for b in output.project_iam_bindings : b if startswith(b.role, "roles/datastore.") && strcontains(b.member, "tilo-connectors@")]) == 1
    error_message = "connectors holds one datastore binding."
  }

  # Unchanged: SEC-02 decrypt rule and the client secret.
  assert {
    condition     = length(output.oauth_token_key_decrypters) == 1 && strcontains(output.oauth_token_key_decrypters[0], "connectors")
    error_message = "Exactly one decrypter on oauth-tokens: connectors (SEC-02)."
  }

  assert {
    condition     = output.secret_accessors["workspace-oauth-client"] == ["serviceAccount:tilo-connectors@${var.project_id}.iam.gserviceaccount.com"]
    error_message = "workspace-oauth-client is readable by connectors only."
  }
}

# ADR-0032 T5b: the tokens database has a deny-all Firestore rules release, shipped by Terraform because firebase.json
# deploys only what a `firebase deploy` names and the CI deployer has no Firebase role. Rules never bind a server (IAM
# does), but a browser or phone SDK must read and write nothing there.
run "SEC_02_the_token_database_has_a_deny_all_rules_release" {
  command = plan

  assert {
    condition     = output.token_rules.release_name == "cloud.firestore/tilo-tokens"
    error_message = "The rules release must be `cloud.firestore/tilo-tokens` (the tokens database), not the default database's."
  }

  assert {
    condition     = length(regexall("allow read, write: if false;", output.token_rules.source)) == 1 && length(regexall("allow ", output.token_rules.source)) == 1
    error_message = "The tokens ruleset has exactly one allow rule and it is `allow read, write: if false;`."
  }

  assert {
    condition     = !strcontains(output.token_rules.source, "if true") && !strcontains(output.token_rules.source, "request.auth") && length(regexall("match ", output.token_rules.source)) == 2
    error_message = "The tokens ruleset is one catch-all deny: no `if true`, no auth-based allow, no per-path match."
  }
}

# ADR-0035 L7: the live connectors add no IAM. The OAuth client secret, the oauth-tokens key and the tilo-tokens database
# stay with connectors; tilo-api (which only starts a connect and calls connectors over RPC) gets none of them.
run "ADR35_L7_tilo_api_holds_no_oauth_secret_kms_or_token_database_access" {
  command = plan

  assert {
    condition     = !contains(flatten(values(output.secret_accessors)), "serviceAccount:tilo-api@${var.project_id}.iam.gserviceaccount.com")
    error_message = "tilo-api reads no Secret Manager secret, least of all workspace-oauth-client."
  }

  assert {
    condition     = !contains(output.oauth_token_key_decrypters, "serviceAccount:tilo-api@${var.project_id}.iam.gserviceaccount.com")
    error_message = "tilo-api may not decrypt the oauth-tokens key (SEC-02)."
  }

  assert {
    condition = alltrue([
      for b in output.project_iam_bindings : b.condition == "resource.name == \"projects/${var.project_id}/databases/(default)\""
      if strcontains(b.member, "tilo-api@") && startswith(b.role, "roles/datastore.")
    ])
    error_message = "tilo-api's Firestore role is limited to the (default) database: it cannot reach tilo-tokens."
  }

  assert {
    condition     = output.secret_accessors["workspace-oauth-client"] == ["serviceAccount:tilo-connectors@${var.project_id}.iam.gserviceaccount.com"]
    error_message = "workspace-oauth-client is readable by connectors only (the accessor binding already exists; L7 adds none)."
  }
}
