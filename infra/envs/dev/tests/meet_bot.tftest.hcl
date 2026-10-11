# Optional guest service: mock plan only, never connects to GCP.
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

run "FR_MTG_09_default_has_no_bot_service" {
  command = plan
  assert {
    condition     = !contains(keys(output.cloud_run_services), "meet-bot")
    error_message = "The bot is opt-in; a default plan must not add it."
  }
}

run "FR_MTG_09_guest_service_is_api_only_bounded_and_keyless" {
  command = plan
  variables { meet_bot_enabled = true }
  assert {
    condition = (
      output.cloud_run_services["meet-bot"].region == "asia-southeast1" &&
      output.cloud_run_services["meet-bot"].ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY" &&
      !output.cloud_run_services["meet-bot"].public &&
      output.cloud_run_services["meet-bot"].min_instance_count == 0 &&
      output.cloud_run_services["meet-bot"].max_instance_count == 1 &&
      output.cloud_run_services["meet-bot"].request_concurrency == 1 &&
      output.cloud_run_services["meet-bot"].timeout == "3600s" &&
      output.cloud_run_services["api"].timeout == "3600s" &&
      output.cloud_run_services["meet-bot"].cpu == "2" &&
      output.cloud_run_services["meet-bot"].memory == "4Gi" &&
      output.cloud_run_services["meet-bot"].cpu_idle
    )
    error_message = "One request-bound guest browser needs the configured compute/deadline and internal ingress."
  }
  assert {
    condition = toset(output.cloud_run_services["meet-bot"].invokers) == toset([
      "serviceAccount:${output.service_accounts["api"]}"
    ])
    error_message = "Only tilo-api may invoke the bot."
  }
  assert {
    condition = alltrue([
      for binding in output.project_iam_bindings :
      contains(["projects/tilo-dev-test/roles/tiloVertexGenerate", "roles/serviceusage.serviceUsageConsumer"], binding.role)
      if binding.member == "serviceAccount:${output.service_accounts["meet-bot"]}"
    ]) && output.service_account_key_count == 0
    error_message = "The guest bot holds no data, OAuth KMS or broad project role, and no service account key."
  }
}
