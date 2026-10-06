# Reusable piece: the one Cloud Scheduler job that fires user schedules
# (FR-AGT-14, PRD 6.3 "Cloud Scheduler: start schedules").
#
#   Cloud Scheduler (every minute, OIDC as tilo-schedule-scheduler)
#     --> POST <target>/internal/schedules/tick on tilo-harness
#
# ONE job for every user schedule, not one per user (quotas, IAM sprawl): the
# tick reads the due schedules from the store. The route takes no body and no
# query, and checks its caller itself (infra/ACCESS.md, route requirements).
#
# The service account is created by the caller (so the target service's
# invoker binding can name it without a dependency cycle). It holds
# run.invoker on the target only, through the service module's
# extra_invokers, and no project-level role.

resource "google_cloud_scheduler_job" "tick" {
  project          = var.project_id
  region           = var.region
  name             = "tilo-schedule-tick"
  description      = "Fire the user schedules that are due (FR-AGT-14)."
  schedule         = "* * * * *"
  time_zone        = "Etc/UTC"
  attempt_deadline = "180s"

  # The next minute is the real retry: the tick is idempotent per slot.
  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "${var.target_uri}${var.path}"

    oidc_token {
      service_account_email = var.service_account_email
      audience              = var.target_uri
    }
  }
}
