## Minimal test wiring for P0-07. See versions.tf.
## Variable contract the acceptance tests in tests/*.tftest.hcl assume.
## The builder ticket must keep these names, types and defaults.

variable "project_id" {
  description = <<-EOT
    GCP project id for the tilo-dev environment.
    NOTE: GCP project ids are globally unique. "tilo-dev" may already be
    taken; the user may need to pick another id and override this default.
  EOT
  type        = string
  default     = "tilo-dev"
}

variable "region" {
  description = "Region for all Tilo services and data (PRD 6.5)."
  type        = string
  default     = "asia-southeast1"
}

variable "billing_account_id" {
  description = "Billing account id the dev project is linked to. No default: must be supplied by the user."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the deployer identity via WIF, e.g. \"owner/tilo\". No default: must be supplied by the user."
  type        = string
}

variable "budget_amount_usd" {
  description = "Monthly billing budget ceiling in USD for tilo-dev (PRD 17.3)."
  type        = number
  default     = 150
}

variable "github_repository_id" {
  description = "Numeric GitHub id of var.github_repository (gh api repos/OWNER/REPO --jq .id). Pinned in the WIF condition so a deleted-and-recreated repo with the same name cannot deploy. No default: must be supplied by the user."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_id))
    error_message = "github_repository_id must be the numeric GitHub repository id."
  }
}

variable "github_repository_owner_id" {
  description = "Numeric GitHub id of the repository owner (gh api repos/OWNER/REPO --jq .owner.id). No default: must be supplied by the user."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id must be the numeric GitHub owner id."
  }
}
