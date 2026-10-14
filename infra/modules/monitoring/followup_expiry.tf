# SEC-REVIEW-37 follow-up 2: alert-only; never applies infrastructure.
resource "google_monitoring_alert_policy" "followup_expiry_failed" {
  project               = var.project_id
  display_name          = "Tilo follow-up expiry sweep failed"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  documentation {
    mime_type = "text/markdown"
    content   = "The API follow-up expiry sweep failed. Inspect the tilo-api revision log and verify all seven follow-up retention composite indexes are READY. Retention cleanup may be incomplete; restore the store or index prerequisite and confirm a successful sweep. This policy alerts only and never retries, deploys, or enables minutes."
  }

  conditions {
    display_name = "Follow-up retention cleanup failed"
    condition_matched_log {
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"tilo-api\" AND (textPayload:\"follow-up expiry sweep failed\" OR jsonPayload.message:\"follow-up expiry sweep failed\")"
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
    auto_close = "1800s"
  }
}
