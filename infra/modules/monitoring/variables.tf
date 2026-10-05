variable "project_id" {
  description = "GCP project the alert policies live in."
  type        = string
}

variable "alert_email" {
  description = "Address that receives every alert (email notification channel). No default."
  type        = string

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.alert_email))
    error_message = "alert_email must be a valid email address."
  }
}

variable "cloud_run_service_names" {
  description = "Cloud Run service names (e.g. tilo-api) the 5xx and latency policies watch."
  type        = list(string)

  validation {
    condition     = length(var.cloud_run_service_names) > 0
    error_message = "Provide at least one Cloud Run service name."
  }
}

variable "events_subscription_id" {
  description = "Pub/Sub subscription id of the events -> BigQuery ledger subscription."
  type        = string
}

variable "error_ratio_threshold" {
  description = "5xx responses / all responses per service above which the error-rate alert fires. Default 0.02 = NFR-23 (error rate > 2%)."
  type        = number
  default     = 0.02
}

variable "latency_p95_threshold_ms" {
  description = "Cloud Run request latency p95 (ms) per service above which the latency alert fires. Default 25000: the loosest p95 target in PRD 17.1 (NFR-03, intake -> approaches <= 25 s); the PRD states no per-service request SLO."
  type        = number
  default     = 25000
}

variable "oldest_unacked_age_seconds" {
  description = "Oldest unacknowledged message age (s) on the events subscription above which the ledger-lag alert fires. Default 600: a stuck BigQuery subscription (the dead-letter signal; no DLQ topic is configured)."
  type        = number
  default     = 600
}

variable "alert_duration_seconds" {
  description = "How long a condition must hold before it fires. Default 300; the window also absorbs one-off errors when a scaled-to-zero service sees little traffic."
  type        = number
  default     = 300
}
