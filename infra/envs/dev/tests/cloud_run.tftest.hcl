# Acceptance tests for P0-07 / PRD-6.5 (Cloud Run services, PRD 6.2, 6.3, 6.5, 6.6).
#
# Runs offline against mock providers -- no credentials, no real project.
#   terraform -chdir=infra/envs/dev init -backend=false
#   terraform -chdir=infra/envs/dev test
#
# Expected root-module output contract (not yet implemented -- these tests
# fail on that missing contract until the builder ticket composes
# infra/modules/service/* into infra/envs/dev/main.tf):
#
#   output "cloud_run_services" -> map(service_name => object({
#     region                : string
#     min_instance_count    : number
#     max_instance_count    : number
#     ingress               : string  # "INGRESS_TRAFFIC_ALL" | "INGRESS_TRAFFIC_INTERNAL_ONLY"
#     cpu_idle              : bool    # true = request-based CPU billing
#     service_account_email : string
#   }))
#
# Keys must be exactly: api, harness, channels, connectors, browser, render,
# sandbox-web (PRD 6.2).

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

run "PRD_6_2_all_seven_services_exist_in_region" {
  command = plan

  assert {
    condition = toset(keys(output.cloud_run_services)) == toset([
      "api", "harness", "channels", "connectors", "browser", "render", "sandbox-web",
    ])
    error_message = "Expected exactly the seven Cloud Run services from PRD 6.2."
  }

  assert {
    condition     = alltrue([for s in values(output.cloud_run_services) : s.region == var.region])
    error_message = "Every Cloud Run service must deploy to var.region (asia-southeast1, PRD 6.5)."
  }
}

run "PRD_6_5_dev_scales_to_zero" {
  command = plan

  assert {
    condition     = alltrue([for s in values(output.cloud_run_services) : s.min_instance_count == 0])
    error_message = "tilo-dev must scale to zero: every service needs min_instance_count = 0 (PRD 6.5 lean infrastructure)."
  }
}

run "PRD_6_6_request_based_cpu_billing" {
  command = plan

  assert {
    condition     = alltrue([for s in values(output.cloud_run_services) : s.cpu_idle == true])
    error_message = "Every Cloud Run service must bill CPU only during request processing (PRD 6.6 lean infrastructure)."
  }
}

run "PRD_6_5_ingress_public_only_for_api_channels_sandbox_web" {
  command = plan

  assert {
    condition = alltrue([
      for name in ["api", "channels", "sandbox-web"] :
      output.cloud_run_services[name].ingress == "INGRESS_TRAFFIC_ALL"
    ])
    error_message = "api, channels and sandbox-web must be publicly reachable (PRD 6.5)."
  }

  assert {
    condition = alltrue([
      for name in ["harness", "connectors", "browser", "render"] :
      output.cloud_run_services[name].ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    ])
    error_message = "harness, connectors, browser and render must not be publicly reachable (PRD 6.5)."
  }
}

run "PRD_6_5_one_least_privilege_service_account_per_service" {
  command = plan

  assert {
    condition     = length(distinct([for s in values(output.cloud_run_services) : s.service_account_email])) == 7
    error_message = "Each of the seven services must run under its own distinct service account (PRD 6.5)."
  }
}

run "PRD_6_5_public_services_invokable_without_google_identity" {
  command = plan

  assert {
    condition = alltrue([
      for name in ["api", "channels", "sandbox-web"] :
      output.cloud_run_services[name].public && contains(output.cloud_run_services[name].invokers, "allUsers")
    ])
    error_message = "api, channels and sandbox-web need allUsers run.invoker; they verify callers themselves (PRD 6.5, SEC-08)."
  }

  assert {
    condition = alltrue([
      for name in ["harness", "connectors", "browser", "render"] :
      !output.cloud_run_services[name].public && !contains(output.cloud_run_services[name].invokers, "allUsers") && !contains(output.cloud_run_services[name].invokers, "allAuthenticatedUsers")
    ])
    error_message = "Internal services must never be invokable by allUsers or allAuthenticatedUsers (PRD 6.5)."
  }
}

run "PRD_6_1_internal_services_invokable_only_by_their_callers" {
  command = plan

  assert {
    condition = toset(output.cloud_run_services["harness"].invokers) == toset([
      "serviceAccount:tilo-api@${var.project_id}.iam.gserviceaccount.com",
      "serviceAccount:tilo-tasks-invoker@${var.project_id}.iam.gserviceaccount.com",
      # Added by P0-07b: Cloud Scheduler renews and polls Gmail watches through harness,
      # the only service that reaches connectors (PRD 6.1). Only this entry was added.
      "serviceAccount:tilo-gmail-scheduler@${var.project_id}.iam.gserviceaccount.com",
    ])
    error_message = "harness must be invokable by exactly tilo-api, the Cloud Tasks OIDC service account and the Gmail Scheduler service account (PRD 6.1)."
  }

  assert {
    condition = alltrue([
      for name in ["connectors", "browser", "render"] :
      output.cloud_run_services[name].invokers == ["serviceAccount:tilo-harness@${var.project_id}.iam.gserviceaccount.com"]
    ])
    error_message = "connectors, browser and render must be invokable only by tilo-harness (PRD 6.1)."
  }
}

run "PRD_6_1_callers_reach_internal_services_through_vpc" {
  command = plan

  assert {
    condition     = output.vpc_egress_subnetwork.private_ip_google_access && output.vpc_egress_subnetwork.region == var.region
    error_message = "The Direct VPC egress subnet must be in var.region with Private Google Access on (PRD 6.1)."
  }

  assert {
    condition = alltrue([
      for name in ["api", "harness"] :
      output.cloud_run_services[name].vpc_egress == "ALL_TRAFFIC" &&
      output.cloud_run_services[name].vpc_network == output.vpc_egress_subnetwork.network &&
      output.cloud_run_services[name].vpc_subnetwork == output.vpc_egress_subnetwork.name
    ])
    error_message = "api and harness call internal-only services, so they need Direct VPC egress with ALL_TRAFFIC (PRD 6.1)."
  }

  assert {
    condition = alltrue([
      for name in ["channels", "connectors", "browser", "render", "sandbox-web"] :
      output.cloud_run_services[name].vpc_egress == null
    ])
    error_message = "Only the callers of internal services (api, harness) route egress through the VPC."
  }
}
