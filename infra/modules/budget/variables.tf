variable "billing_account_id" {
  description = "Billing account id the project is linked to."
  type        = string
}

variable "project_number" {
  description = "GCP project number the budget scopes to."
  type        = string
}

variable "display_name" {
  description = "Budget display name."
  type        = string
}

variable "amount_usd" {
  description = "Monthly budget ceiling in USD (PRD 17.3)."
  type        = number
}

variable "threshold_percentages" {
  description = "Alert thresholds as fractions, e.g. [0.5, 0.9, 1.0]."
  type        = list(number)
  default     = [0.5, 0.9, 1.0]
}
