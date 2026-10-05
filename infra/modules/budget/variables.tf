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
  description = "Monthly budget ceiling (PRD 17.3), in var.currency_code units despite the name."
  type        = number
}

variable "currency_code" {
  description = "Currency of amount_usd. Must equal the billing account's currency or the API rejects the budget."
  type        = string
  default     = "USD"
}

variable "threshold_percentages" {
  description = "Alert thresholds as fractions, e.g. [0.5, 0.9, 1.0]."
  type        = list(number)
  default     = [0.5, 0.9, 1.0]
}
