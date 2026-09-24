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
