# Reusable piece: a billing budget with 50/90/100% alerts (PRD 6.5 lean
# infrastructure, 17.3 cost ceilings).

resource "google_billing_budget" "this" {
  billing_account = var.billing_account_id
  display_name    = var.display_name

  budget_filter {
    projects = ["projects/${var.project_number}"]
    # Track gross spend. With the default (INCLUDE_ALL_CREDITS) free-trial credits
    # are subtracted first, so net spend stays 0 and no alert fires until they run out.
    credit_types_treatment = "EXCLUDE_ALL_CREDITS"
  }

  amount {
    specified_amount {
      currency_code = var.currency_code
      units         = tostring(var.amount_usd)
    }
  }

  dynamic "threshold_rules" {
    for_each = var.threshold_percentages

    content {
      threshold_percent = threshold_rules.value
    }
  }
}
