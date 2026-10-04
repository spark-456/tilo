variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "Cloud Scheduler region."
  type        = string
}

variable "target_uri" {
  description = "run.app URL of the Cloud Run service that handles Gmail push, renew and poll (tilo-channels)."
  type        = string
}

variable "push_service_account_name" {
  description = "Resource name (projects/.../serviceAccounts/...) of the service account Pub/Sub signs the push token as."
  type        = string
}

variable "push_service_account_email" {
  description = "Email of that push service account. The target must verify this as the OIDC email claim."
  type        = string
}

variable "scheduler_service_account_email" {
  description = "Email of the service account Cloud Scheduler uses; it needs run.invoker on the target only."
  type        = string
}

variable "pubsub_service_agent_email" {
  description = "Email of the Pub/Sub service agent."
  type        = string
}

variable "push_path" {
  description = "Path on the target that receives Pub/Sub pushes. Does not exist in services/channels yet (dependency)."
  type        = string
  default     = "/internal/gmail/push"
}

variable "renew_path" {
  description = "Path on the target that calls MailWatcher.renew_due(). Does not exist yet (dependency)."
  type        = string
  default     = "/internal/gmail/renew"
}

variable "poll_path" {
  description = "Path on the target that calls MailWatcher.poll_due(). Does not exist yet (dependency)."
  type        = string
  default     = "/internal/gmail/poll"
}

variable "renew_schedule" {
  description = "Cron (UTC) for the watch renewal. Daily, as Google recommends; a watch lasts 7 days."
  type        = string
  default     = "0 3 * * *"
}

variable "poll_schedule" {
  description = "Cron (UTC) for the polling fallback. Every 5 minutes; Scheduler's minimum is 1 minute."
  type        = string
  default     = "*/5 * * * *"
}
