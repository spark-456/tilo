# Acceptance tests for INFRA-SITTING2 (sitting2.tf, docs/runbooks/infra-sitting-2.md): mock plan only, never connects.
#   terraform -chdir=infra/envs/dev init -backend=false
#   terraform -chdir=infra/envs/dev test

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

run "FR_MEM_09_api_deletes_artifact_bytes_with_a_one_permission_role_on_artifacts_only" {
  command = plan

  assert {
    condition     = output.artifact_delete_role_permissions == toset(["storage.objects.delete"])
    error_message = "The artifact delete role holds storage.objects.delete and nothing else."
  }

  assert {
    condition = toset([for k in keys(output.service_storage_grants) : k if strcontains(k, "tiloArtifactObjectDelete")]) == toset([
      "artifacts::api::projects/tilo-dev-test/roles/tiloArtifactObjectDelete",
    ])
    error_message = "The delete role is bound once: api on the artifacts bucket. Never archive or snapshots, never another service."
  }
}

run "FR_MEM_04_archive_stays_create_only_for_api_no_delete_no_update" {
  command = plan

  assert {
    condition = alltrue([
      for k in keys(output.service_storage_grants) :
      contains(["roles/storage.objectCreator", "roles/storage.objectViewer"], split("::", k)[2])
      if startswith(k, "archive::")
    ])
    error_message = "Every grant on the archive bucket is objectCreator or objectViewer: nobody can overwrite or delete a record."
  }

  assert {
    condition     = output.storage_buckets["archive"].lifecycle_rule_count == 1 && output.storage_buckets["archive"].versioning_enabled == false
    error_message = "The archive bucket keeps its single 30-day delete rule and no versioning."
  }
}

run "BQ_PA06B_2_firestore_ttl_policies_on_the_three_expiring_collections" {
  command = plan

  assert {
    condition = output.firestore_ttl_fields == {
      limiter_counters = "expires_at"
      limiter_keys     = "expires_at"
      link_nonces      = "expires_at"
    }
    error_message = "TTL policies: limiter_counters, limiter_keys and link_nonces on expires_at, and no other collection."
  }
}

run "P870_test_only_cloud_build_identity_reads_source_and_writes_logs_only" {
  command = plan

  assert {
    condition     = output.cloudbuild_tests_service_account_email == "tilo-cloudbuild-tests@tilo-dev-test.iam.gserviceaccount.com"
    error_message = "The test-only gate identity is tilo-cloudbuild-tests."
  }

  assert {
    condition = toset([for g in output.cloudbuild_tests_grants : "${g.scope}|${g.resource}|${g.role}"]) == toset([
      "project|tilo-dev-test|roles/logging.logWriter",
      "storage_bucket|tilo-dev-test-cloudbuild-staging|roles/storage.objectViewer",
    ])
    error_message = "The test-only identity holds logWriter and objectViewer on the staging bucket: no deploy, registry, act-as or secret access."
  }

  assert {
    condition     = !anytrue([for b in output.project_iam_bindings : strcontains(b.member, "tilo-cloudbuild-tests@") && b.role != "roles/logging.logWriter"])
    error_message = "No project role other than logWriter for the test-only identity."
  }

  assert {
    condition     = length(output.cloudbuild_grants) == 17
    error_message = "tilo-cloudbuild itself is unchanged (17 bindings): the gate keeps it until the user chooses."
  }
}

run "INFRA_SITTING2_the_bot_stays_off_by_default_and_channels_stay_public" {
  command = plan

  assert {
    condition     = !contains(keys(output.cloud_run_services), "meet-bot")
    error_message = "meet_bot_enabled stays false by default."
  }

  assert {
    condition     = output.cloud_run_services["channels"].ingress == "INGRESS_TRAFFIC_ALL" && output.cloud_run_services["channels"].public
    error_message = "tilo-channels receives Gmail and WhatsApp webhooks from the internet, so it stays public; /internal/push/send checks its caller itself."
  }
}
