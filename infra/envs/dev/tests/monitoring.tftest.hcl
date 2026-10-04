# Acceptance tests for P0-07b (PRD 6.3 APIs, Logging/Monitoring/Trace SLO
# alerts, NFR-23). Offline against mock providers.
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

run "PRD_6_3_required_apis_cover_the_prd_services" {
  command = plan

  assert {
    condition = alltrue([
      for api in [
        "modelarmor.googleapis.com", "cloudscheduler.googleapis.com", "identitytoolkit.googleapis.com",
        "firebaseappcheck.googleapis.com", "monitoring.googleapis.com", "cloudtrace.googleapis.com",
        "logging.googleapis.com", "gmail.googleapis.com", "calendar-json.googleapis.com", "drive.googleapis.com",
      ] : contains(output.enabled_apis, api)
    ])
    error_message = "PRD 6.3 services and the three Workspace APIs must be enabled."
  }

  assert {
    condition     = !contains(output.enabled_apis, "texttospeech.googleapis.com") && !contains(output.enabled_apis, "speech.googleapis.com")
    error_message = "Speech APIs are not enabled by this ticket."
  }
}

run "NFR_23_alert_email_goes_to_var_alert_email" {
  command = plan

  assert {
    condition     = output.monitoring.notification_email == "alerts@example.com"
    error_message = "The email notification channel must use var.alert_email."
  }
}

run "NFR_23_alert_policies_exist_with_documented_default_thresholds" {
  command = plan

  assert {
    condition     = toset(keys(output.monitoring.alert_policies)) == toset(["run_5xx_ratio", "run_latency_p95", "events_oldest_unacked"])
    error_message = "Expected the 5xx ratio, latency p95 and events backlog alert policies."
  }

  assert {
    condition     = output.monitoring.alert_policies.run_5xx_ratio.threshold_value == 0.02
    error_message = "5xx ratio default must be 2% (NFR-23)."
  }

  assert {
    condition     = output.monitoring.alert_policies.run_latency_p95.threshold_value == 25000
    error_message = "Latency p95 default must be 25000 ms (loosest PRD 17.1 p95 target)."
  }

  assert {
    condition     = output.monitoring.alert_policies.events_oldest_unacked.threshold_value == 600
    error_message = "Events backlog default must be 600 s."
  }
}

run "NFR_23_5xx_policy_watches_every_cloud_run_service" {
  command = plan

  assert {
    condition = alltrue([
      for s in keys(output.cloud_run_services) :
      strcontains(output.monitoring.alert_policies.run_5xx_ratio.filter, "tilo-${s}")
    ])
    error_message = "The 5xx policy filter must cover all seven Cloud Run services."
  }

  assert {
    condition     = strcontains(output.monitoring.alert_policies.events_oldest_unacked.filter, "tilo-events-to-bigquery")
    error_message = "The backlog policy must watch the events subscription."
  }
}

run "NFR_23_thresholds_are_variable_driven" {
  command = plan

  module {
    source = "../../modules/monitoring"
  }

  variables {
    project_id                 = "tilo-dev-test"
    alert_email                = "ops@example.com"
    cloud_run_service_names    = ["tilo-api"]
    events_subscription_id     = "sub"
    error_ratio_threshold      = 0.05
    latency_p95_threshold_ms   = 1000
    oldest_unacked_age_seconds = 30
  }

  assert {
    condition = (
      output.alert_policies.run_5xx_ratio.threshold_value == 0.05 &&
      output.alert_policies.run_latency_p95.threshold_value == 1000 &&
      output.alert_policies.events_oldest_unacked.threshold_value == 30
    )
    error_message = "Thresholds must follow the module variables."
  }
}

run "NFR_23_invalid_alert_email_rejected" {
  command = plan

  variables {
    alert_email = "not-an-email"
  }

  expect_failures = [var.alert_email]
}

run "P0_07b_secret_accessors_output_is_config_derived" {
  command = plan

  assert {
    condition     = length(output.secret_accessors) == 4 && alltrue([for s, m in output.secret_accessors : length(m) == 1])
    error_message = "secret_accessors must list one accessor per secret, from config (stable across refresh)."
  }
}
