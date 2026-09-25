variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deployer identity, e.g. \"owner/tilo\"."
  type        = string
}

variable "github_repository_id" {
  description = "Numeric GitHub id of var.github_repository (immutable across renames)."
  type        = string
}

variable "github_repository_owner_id" {
  description = "Numeric GitHub id of the repository owner (immutable across renames)."
  type        = string
}
