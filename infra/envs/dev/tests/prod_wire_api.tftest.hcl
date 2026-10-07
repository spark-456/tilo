# Acceptance tests for PROD-WIRE slice 3 (ADR-0026: tilo-api keeps its state in Firestore, one writer instance).
#
# Runs offline against mock providers -- no credentials, no real project.
#   terraform -chdir=infra/envs/dev init -backend=false
#   terraform -chdir=infra/envs/dev test
#
# Contract the builder must add (names and shapes pinned here, mirroring cloud_run.tftest.hcl):
#
#   infra/modules/service  var.services entries gain two optional attributes
#     cpu_idle = optional(bool, true)             # request-based CPU billing unless an entry says false
#     env      = optional(map(string), {})        # plain container environment variables, no secrets
#   and the module output `services` (so root output.cloud_run_services) reports, per service,
#     cpu_idle : bool          # what the entry asked for, no longer a literal true
#     env      : map(string)   # exactly the entry's env ({} when it has none)
#
#   infra/envs/dev/main.tf, the api entry:
#     max_instance_count = 1   # ADR-0026: one instance is the one writer (a lease, an in-process cache)
#     cpu_idle           = false   # background work (a run's thread, the lease heartbeat) needs CPU between requests
#     env = { TILO_API_STORE = "firestore", TILO_PEOPLE_STORE = "firestore", TILO_FIRESTORE_PROJECT = var.project_id }
#
# Every other service keeps cpu_idle = true, no env, and its own max_instance_count (harness and channels 3, the rest 2). min_instance_count stays 0 for all
# (PRD 6.5; cloud_run.tftest.hcl). No secret, no LIVE and no TILO_JUDGE_LIVE: those are the user's, never Terraform's
# (the exact env map below leaves no room for them).

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

run "PROD_WIRE_3_api_has_cpu_between_requests" {
  command = plan

  assert {
    condition     = output.cloud_run_services["api"].cpu_idle == false
    error_message = "tilo-api needs CPU allocated outside requests (cpu_idle = false): a run's thread and the writer lease heartbeat."
  }
}

run "PROD_WIRE_3_api_opens_the_firestore_doors_and_nothing_else" {
  command = plan

  assert {
    condition = output.cloud_run_services["api"].env == tomap({
      TILO_API_STORE         = "firestore"
      TILO_PEOPLE_STORE      = "firestore"
      TILO_FIRESTORE_PROJECT = var.project_id
    })
    error_message = "tilo-api's environment is exactly TILO_API_STORE, TILO_PEOPLE_STORE (both firestore) and TILO_FIRESTORE_PROJECT = the project; no secret, no LIVE, no TILO_JUDGE_LIVE."
  }

  assert {
    condition     = !contains(keys(output.cloud_run_services["api"].env), "LIVE") && !contains(keys(output.cloud_run_services["api"].env), "TILO_JUDGE_LIVE")
    error_message = "Live model calls are the user's switch, never Terraform's (EFF-01)."
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
      for name in ["harness", "channels", "connectors", "browser", "render", "sandbox-web"] :
      length(output.cloud_run_services[name].env) == 0
    ])
    error_message = "No other service gets an environment variable in this slice."
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
