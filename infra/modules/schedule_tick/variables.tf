variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "Cloud Scheduler region."
  type        = string
}

variable "target_uri" {
  description = "run.app URL of tilo-api: the service the tick calls and the OIDC audience."
  type        = string
}

variable "service_account_email" {
  description = "Email of tilo-schedule-scheduler, the identity the job runs as. It holds no IAM: the target is public and checks the token itself."
  type        = string
}

variable "path" {
  description = "Path on the target (api) that fires the due schedules."
  type        = string
  default     = "/internal/schedules/tick"
}
