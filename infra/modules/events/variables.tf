variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "project_number" {
  description = "GCP project number, used to address the Pub/Sub service agent."
  type        = string
}

variable "region" {
  description = "BigQuery dataset location."
  type        = string
}
