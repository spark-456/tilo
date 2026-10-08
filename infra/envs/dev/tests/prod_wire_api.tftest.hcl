# Acceptance tests for PROD-WIRE slice 3 (ADR-0026: tilo-api keeps its state in Firestore, one writer instance).
#
# Runs offline against mock providers -- no credentials, no real project.
#   terraform -chdir=infra/envs/dev init -backend=false
#   terraform -chdir=infra/envs/dev test
#
# Contract (names and shapes pinned here, mirroring cloud_run.tftest.hcl):
#
#   infra/modules/service  var.services entries take `cpu_idle = optional(bool, true)`, rendered on both Cloud Run
#   resources (the managed one and the ignore_env one tilo-api lives in), and the module output `services` reports
#   the real cpu_idle per service.
#
#   infra/envs/dev/main.tf, the api entry:
#     max_instance_count = 1                     # ADR-0026: one instance is the one writer
#     cpu_idle           = !var.api_durable_stores
#     ignore_env         = true                  # the store switches are gcloud runtime env (docs/deploy-dev.md)
#
# Every other service keeps cpu_idle = true and its own max_instance_count (harness and channels 3, the rest 2).
# min_instance_count stays 0 for all (PRD 6.5). Terraform sets no env on tilo-api at all, so it can never set the
# store switches, a secret, LIVE or TILO_JUDGE_LIVE (tests/repo/test_PROD_WIRE_3_api_service_terraform.py).

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

run "PROD_WIRE_3_api_is_one_writer_instance" {
  command = plan

  assert {
    condition     = output.cloud_run_services["api"].max_instance_count == 1
    error_message = "tilo-api must run at most one instance (ADR-0026: one writer, one lease, one in-process cache)."
  }

  assert {
    condition     = output.cloud_run_services["api"].min_instance_count == 0
    error_message = "tilo-api still scales to zero (PRD 6.5): min_instance_count stays 0."
  }
}

# Security round 1 (ADR-0023, ADR-0026 Proposed): the durable stores are the user's opt-in. The variable
# `api_durable_stores` (bool, default false, infra/envs/dev/variables.tf) switches the api's always-on CPU; the store
# switches are the user's gcloud step. max_instance_count = 1 is unconditional.

run "PROD_WIRE_3_default_api_has_request_based_cpu" {
  command = plan

  assert {
    condition     = output.cloud_run_services["api"].cpu_idle == true
    error_message = "By default tilo-api keeps request-based CPU billing (PRD 6.6)."
  }

  assert {
    condition     = output.cloud_run_services["api"].max_instance_count == 1
    error_message = "tilo-api runs at most one instance whatever the switch says (ADR-0026)."
  }
}

run "PROD_WIRE_3_opt_in_api_has_cpu_between_requests" {
  command = plan

  variables {
    api_durable_stores = true
  }

  assert {
    condition     = output.cloud_run_services["api"].cpu_idle == false
    error_message = "With api_durable_stores = true tilo-api needs CPU allocated outside requests (cpu_idle = false): a run's thread and the writer lease heartbeat."
  }

  assert {
    condition     = output.cloud_run_services["api"].max_instance_count == 1 && output.cloud_run_services["api"].min_instance_count == 0
    error_message = "One instance at most (ADR-0026), still scaling to zero (PRD 6.5)."
  }
}

run "PROD_WIRE_3_every_other_service_is_unchanged" {
  command = plan

  assert {
    condition = alltrue([
      for name in ["harness", "channels", "connectors", "browser", "render", "sandbox-web"] :
      output.cloud_run_services[name].cpu_idle == true
    ])
    error_message = "Only tilo-api leaves request-based CPU billing; harness and every other service keep cpu_idle = true (PRD 6.6)."
  }

  assert {
    condition = alltrue([
      for name in ["harness", "channels"] : output.cloud_run_services[name].max_instance_count == 3
      ]) && alltrue([
      for name in ["connectors", "browser", "render", "sandbox-web"] : output.cloud_run_services[name].max_instance_count == 2
    ])
    error_message = "The other services keep their max_instance_count (harness and channels 3; connectors, browser, render, sandbox-web 2)."
  }
}
