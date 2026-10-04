# Reusable piece: Gmail push notifications and the Cloud Scheduler jobs that
# keep them alive (FR-CHN-08, PRD 6.3 "Pub/Sub: Gmail push notifications",
# "Cloud Scheduler: autopilot polling fallback").
#
#   Gmail users.watch --> topic (only gmail-api-push@system may publish)
#     --> push subscription with an OIDC token --> <target>/<push_path>
#   Cloud Scheduler (OIDC, run.invoker on the scheduler target only) --> POST
#     renew_path (re-watch, daily) and poll_path (polling fallback) on the
#     scheduler target (tilo-harness: only harness reaches connectors).
#
# The two service accounts are created by the caller (so the target service's
# invoker bindings can name them without a dependency cycle).

locals {
  jobs = {
    renew = { schedule = var.renew_schedule, path = var.renew_path, description = "Re-issue users.watch before it lapses (FR-CHN-08)." }
    poll  = { schedule = var.poll_schedule, path = var.poll_path, description = "Polling fallback: read Gmail history for stale watches (FR-CHN-08)." }
  }
}

resource "google_pubsub_topic" "gmail" {
  project = var.project_id
  name    = "tilo-gmail-notifications"
}

# Gmail publishes as this Google-owned account; grant it on THIS topic only.
resource "google_pubsub_topic_iam_member" "gmail_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.gmail.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:gmail-api-push@system.gserviceaccount.com"
}

# Pub/Sub signs the push OIDC token as the push service account. Only the
# OpenID-token role is needed (getOpenIdToken), not full token creation.
resource "google_service_account_iam_member" "pubsub_signs_push_token" {
  service_account_id = var.push_service_account_name
  role               = "roles/iam.serviceAccountOpenIdTokenCreator"
  member             = "serviceAccount:${var.pubsub_service_agent_email}"
}

resource "google_pubsub_subscription" "gmail_push" {
  project = var.project_id
  name    = "tilo-gmail-push"
  topic   = google_pubsub_topic.gmail.id

  ack_deadline_seconds       = 60
  message_retention_duration = "86400s"

  push_config {
    push_endpoint = "${var.push_target_uri}${var.push_path}"
    oidc_token {
      service_account_email = var.push_service_account_email
      audience              = var.push_target_uri
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  # Never expire for inactivity (the default deletes it after 31 idle days).
  expiration_policy {
    ttl = ""
  }

  depends_on = [google_service_account_iam_member.pubsub_signs_push_token]
}

resource "google_cloud_scheduler_job" "gmail" {
  for_each = local.jobs

  project          = var.project_id
  region           = var.region
  name             = "tilo-gmail-${each.key}"
  description      = each.value.description
  schedule         = each.value.schedule
  time_zone        = "Etc/UTC"
  attempt_deadline = "180s"

  retry_config {
    retry_count = 3
  }

  http_target {
    http_method = "POST"
    uri         = "${var.scheduler_target_uri}${each.value.path}"

    oidc_token {
      service_account_email = var.scheduler_service_account_email
      audience              = var.scheduler_target_uri
    }
  }
}
