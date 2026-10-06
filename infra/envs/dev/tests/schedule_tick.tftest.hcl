# Acceptance tests for FR-AGT-14 (scheduled runs, "Clock Tower"; PRD 6.3 Cloud Scheduler, 8.6). Requirement id: FR-AGT-14.
#
#   terraform -chdir=infra/envs/dev test
#
# ONE Cloud Scheduler job for every user schedule (not one per user): `tilo-schedule-tick`, every minute, POSTs
# /internal/schedules/tick on tilo-harness with an OIDC token for the new service account `tilo-schedule-scheduler`.
# That account holds run.invoker on harness only and nothing else. The route checks its caller itself
# (services/harness/tests/test_FR_AGT_14_tick_route.py); this file pins the planned infrastructure.
#
# Output contract the builder must add to infra/envs/dev/outputs.tf (name and shape pinned here):
#
#   output "schedule_tick" -> object({
#     job_name        = string   # "tilo-schedule-tick"
#     schedule        = string   # "* * * * *"
#     time_zone       = string   # "Etc/UTC" or "UTC"
#     path            = string   # "/internal/schedules/tick"
#     http_method     = string   # "POST"
#     retry_count     = number   # 1
#     service_account = string   # "tilo-schedule-scheduler@<project>.iam.gserviceaccount.com"
#     audience        = string   # the harness base URL the job calls (non-empty; the uri starts with it)
#     uri             = string   # <harness URL>/internal/schedules/tick
#   })
#
# The harness invoker list in cloud_run.tftest.hcl ("PRD_6_1_internal_services_invokable_only_by_their_callers") must also
# gain "serviceAccount:tilo-schedule-scheduler@..." (the only entry added). That change is deliberate, like the Gmail one.
# Ambiguity resolved: the job's time zone is UTC (brief); `Etc/UTC` (as the Gmail jobs) and `UTC` are both accepted.

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

run "FR_AGT_14_one_every_minute_job_posts_the_tick_route_as_the_schedule_scheduler" {
  command = plan

  assert {
    condition     = output.schedule_tick.job_name == "tilo-schedule-tick" && output.schedule_tick.schedule == "* * * * *"
    error_message = "One Cloud Scheduler job, tilo-schedule-tick, runs every minute (the Scheduler floor)."
  }

  assert {
    condition     = contains(["Etc/UTC", "UTC"], output.schedule_tick.time_zone)
    error_message = "The tick is scheduled in UTC."
  }

  assert {
    condition     = output.schedule_tick.http_method == "POST" && output.schedule_tick.path == "/internal/schedules/tick" && output.schedule_tick.retry_count == 1
    error_message = "POST /internal/schedules/tick, retry_count 1."
  }

  assert {
    condition     = output.schedule_tick.service_account == "tilo-schedule-scheduler@${var.project_id}.iam.gserviceaccount.com"
    error_message = "The tick authenticates as tilo-schedule-scheduler, not the Gmail scheduler or the Cloud Tasks identity."
  }

  # audience and uri come from the Cloud Run service URI, which is unknown at plan time under mock_provider (a
  # condition on it is skipped as "Unknown condition value", skipping the invoker runs below). Their equality (the
  # audience is the harness base URL, the uri is that plus the tick path) is pinned statically in
  # tests/repo/test_FR_AGT_14_schedule_tick_terraform.py.
}

run "FR_AGT_14_the_schedule_scheduler_may_invoke_harness_only" {
  command = plan

  assert {
    condition = length([
      for m in output.cloud_run_services["harness"].invokers : m
      if m == "serviceAccount:tilo-schedule-scheduler@${var.project_id}.iam.gserviceaccount.com"
    ]) == 1
    error_message = "tilo-schedule-scheduler holds run.invoker on tilo-harness exactly once."
  }

  assert {
    condition = alltrue([
      for s in ["api", "channels", "connectors", "browser", "render", "sandbox-web"] :
      !contains(output.cloud_run_services[s].invokers, "serviceAccount:tilo-schedule-scheduler@${var.project_id}.iam.gserviceaccount.com")
    ])
    error_message = "The schedule scheduler may invoke tilo-harness only."
  }

  assert {
    condition = toset(output.cloud_run_services["harness"].invokers) == toset([
      "serviceAccount:tilo-api@${var.project_id}.iam.gserviceaccount.com",
      "serviceAccount:tilo-tasks-invoker@${var.project_id}.iam.gserviceaccount.com",
      "serviceAccount:tilo-gmail-scheduler@${var.project_id}.iam.gserviceaccount.com",
      "serviceAccount:tilo-schedule-scheduler@${var.project_id}.iam.gserviceaccount.com",
    ])
    error_message = "harness is invokable by exactly tilo-api, the Cloud Tasks identity, the Gmail scheduler and the schedule scheduler."
  }
}

run "FR_AGT_14_the_other_scheduler_identities_do_not_gain_the_new_route_by_a_new_binding" {
  command = plan

  assert {
    condition = alltrue([
      for s in ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"] :
      !contains(output.cloud_run_services[s].developers, "serviceAccount:tilo-schedule-scheduler@${var.project_id}.iam.gserviceaccount.com")
    ])
    error_message = "The schedule scheduler may not deploy any service (no run.developer)."
  }
}
