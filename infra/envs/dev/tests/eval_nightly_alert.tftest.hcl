# Acceptance pins for EFF-05c: the failed-nightly-eval alert. Offline against mock providers.
#   terraform -chdir=infra/envs/dev test
# Separate from monitoring.tftest.hcl, whose `alert_policies` pin stays at the three NFR-23 keys.

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

run "EFF_05c_alert_watches_failed_executions_of_the_nightly_job" {
  command = plan

  assert {
    condition = (
      output.monitoring.eval_nightly_alert_policy.display_name == "Tilo nightly eval job failed" &&
      output.monitoring.eval_nightly_alert_policy.threshold_value == 0 &&
      strcontains(output.monitoring.eval_nightly_alert_policy.filter, "job_name=\"tilo-eval-nightly\"") &&
      strcontains(output.monitoring.eval_nightly_alert_policy.filter, "metric.labels.result=\"failed\"")
    )
    error_message = "The alert must fire on any failed execution of the tilo-eval-nightly Cloud Run job."
  }

  assert {
    condition     = toset(keys(output.monitoring.alert_policies)) == toset(["run_5xx_ratio", "run_latency_p95", "events_oldest_unacked"])
    error_message = "The NFR-23 alert_policies output stays at its three keys."
  }
}

run "EFF_05c_job_name_is_variable_driven" {
  command = plan

  module {
    source = "../../modules/monitoring"
  }

  variables {
    project_id              = "tilo-dev-test"
    alert_email             = "ops@example.com"
    cloud_run_service_names = ["tilo-api"]
    events_subscription_id  = "sub"
    eval_nightly_job_name   = "other-job"
  }

  assert {
    condition     = strcontains(output.eval_nightly_alert_policy.filter, "job_name=\"other-job\"")
    error_message = "The alert filter must follow eval_nightly_job_name."
  }
}
