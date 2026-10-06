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

# Owner cost alerts (NFR-27): the metering code writes one redacted JSON line per alert
# (`"event": "cost_alert"`, kind uid_cap_80 / uid_cap_100 / global_daily, packages/metering). The log-based
# counter below turns each line into a data point and the policy emails the owner. Alert-only: nothing here
# blocks or changes spend.
resource "google_logging_metric" "cost_alert" {
  project     = var.project_id
  name        = "tilo_cost_alert"
  description = "Count of NFR-27 owner cost alert log lines, by kind."
  filter      = "resource.type=\"cloud_run_revision\" AND logName:\"run.googleapis.com%2Fstdout\" AND jsonPayload.event=\"cost_alert\" AND jsonPayload.kind=(\"uid_cap_80\" OR \"uid_cap_100\" OR \"global_daily\")"

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Tilo cost alerts"

    labels {
      key         = "kind"
      value_type  = "STRING"
      description = "uid_cap_80, uid_cap_100 or global_daily."
    }
  }

  label_extractors = {
    kind = "EXTRACT(jsonPayload.kind)"
  }
}

resource "google_monitoring_alert_policy" "cost_alert" {
  project               = var.project_id
  display_name          = "Tilo owner cost alert"
  combiner              = "OR"
  notification_channels = [google_monitoring_notification_channel.email.id]

  documentation {
    mime_type = "text/markdown"
    content   = "A Tilo cost alert line was logged (NFR-27): a uid reached 80% or 100% of its lifetime spend cap, or the day's global spend passed its threshold. Open Logs Explorer and filter on jsonPayload.event=\"cost_alert\" for the kind, the uid_ref digest (never the raw uid) and the figures. Alert-only: spend is not blocked."
  }

  conditions {
    display_name = "Cost alert logged"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/tilo_cost_alert\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      # Non-zero: the API rejects evaluation_missing_data with a 0s duration. One alert line keeps the 300s sum above 0 for 300s, so 60s still fires on a single event.
      duration = "60s"

      evaluation_missing_data = "EVALUATION_MISSING_DATA_INACTIVE"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.kind"]
      }

      trigger {
        count = 1
      }
    }
  }

  # No notification_rate_limit: the API documents it for log-match policies only; this is a metric threshold policy.
  alert_strategy {
    auto_close = "1800s"
  }

  depends_on = [google_logging_metric.cost_alert]
}
