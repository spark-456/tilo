variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deployer identity, e.g. \"owner/tilo\"."
  type        = string
}
