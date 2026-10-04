# Reusable piece: email notification channel and SLO alert policies
# (PRD 6.3 "Logging, Monitoring, Trace" SLO alerts, NFR-23). Metric-based
# alerts only: no uptime checks, so nothing here keeps a scale-to-zero Cloud
# Run service warm and nothing runs while the system is idle.

locals {
  service_regex = join("|", var.cloud_run_service_names)
  run_filter    = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=monitoring.regex.full_match(\"${local.service_regex}\")"
}

resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "Tilo alerts (email)"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

# 5xx ratio per Cloud Run service (NFR-23: error rate > 2%).
resource "google_monitoring_alert_policy" "run_5xx_ratio" {
  project               = var.project_id
  display_name          = "Tilo Cloud Run 5xx ratio"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  documentation {
    mime_type = "text/markdown"
    content   = "More than ${var.error_ratio_threshold * 100}% of requests to a Tilo Cloud Run service returned 5xx for ${var.alert_duration_seconds}s (NFR-23)."
  }

  conditions {
    display_name = "5xx ratio above threshold"

    condition_threshold {
      filter             = "metric.type=\"run.googleapis.com/request_count\" AND ${local.run_filter} AND metric.labels.response_code_class=\"5xx\""
      denominator_filter = "metric.type=\"run.googleapis.com/request_count\" AND ${local.run_filter}"
      comparison         = "COMPARISON_GT"
      threshold_value    = var.error_ratio_threshold
      duration           = "${var.alert_duration_seconds}s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.service_name"]
      }

      denominator_aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.label.service_name"]
      }

      trigger {
        count = 1
      }
    }
  }
}

# Request latency p95 per Cloud Run service.
resource "google_monitoring_alert_policy" "run_latency_p95" {
  project               = var.project_id
  display_name          = "Tilo Cloud Run latency p95"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  documentation {
    mime_type = "text/markdown"
    content   = "Request latency p95 of a Tilo Cloud Run service exceeded ${var.latency_p95_threshold_ms} ms for ${var.alert_duration_seconds}s (PRD 17.1)."
  }

  conditions {
    display_name = "Request latency p95 above threshold"

    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_latencies\" AND ${local.run_filter}"
      comparison      = "COMPARISON_GT"
      threshold_value = var.latency_p95_threshold_ms
      duration        = "${var.alert_duration_seconds}s"

      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_PERCENTILE_95"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.label.service_name"]
      }

      trigger {
        count = 1
      }
    }
  }
}

# Ledger lag: the events -> BigQuery subscription is not draining.
resource "google_monitoring_alert_policy" "events_oldest_unacked" {
  project               = var.project_id
  display_name          = "Tilo events subscription backlog"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  documentation {
    mime_type = "text/markdown"
    content   = "The oldest unacknowledged message on ${var.events_subscription_id} is older than ${var.oldest_unacked_age_seconds}s: events are not reaching the BigQuery ledger (PRD 13.2)."
  }

  conditions {
    display_name = "Oldest unacked message age above threshold"

    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\" AND resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${var.events_subscription_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.oldest_unacked_age_seconds
      duration        = "${var.alert_duration_seconds}s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }

      trigger {
        count = 1
      }
    }
  }
}
