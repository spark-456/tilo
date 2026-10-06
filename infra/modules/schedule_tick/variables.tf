variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "Cloud Scheduler region."
  type        = string
}

variable "target_uri" {
  description = "run.app URL of tilo-harness: the service the tick calls and the OIDC audience."
  type        = string
}

variable "service_account_email" {
  description = "Email of tilo-schedule-scheduler, the identity the job runs as. It needs run.invoker on the target only."
  type        = string
}

variable "path" {
  description = "Path on the target (harness) that fires the due schedules."
  type        = string
  default     = "/internal/schedules/tick"
}
