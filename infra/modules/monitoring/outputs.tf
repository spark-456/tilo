output "notification_channel_email" {
  description = "Address the email notification channel sends to."
  value       = google_monitoring_notification_channel.email.labels["email_address"]
}

output "alert_policies" {
  description = "Policy key => {display_name, threshold_value, duration} (config values, known at plan time)."
  value = {
    for k, p in {
      run_5xx_ratio         = google_monitoring_alert_policy.run_5xx_ratio
      run_latency_p95       = google_monitoring_alert_policy.run_latency_p95
      events_oldest_unacked = google_monitoring_alert_policy.events_oldest_unacked
      } : k => {
      display_name    = p.display_name
      threshold_value = p.conditions[0].condition_threshold[0].threshold_value
      duration        = p.conditions[0].condition_threshold[0].duration
      filter          = p.conditions[0].condition_threshold[0].filter
    }
  }
}

output "cost_alert_policy" {
  description = "NFR-27 owner cost alert: policy display name and the log-based metric it reads (kept apart from alert_policies, which pins the three NFR-23 keys)."
  value = {
    display_name = google_monitoring_alert_policy.cost_alert.display_name
    metric_name  = google_logging_metric.cost_alert.name
  }
}
