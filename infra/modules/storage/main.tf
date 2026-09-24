# Reusable piece: Cloud Storage buckets with uniform bucket-level access and
# a lifecycle rule per bucket (PRD 6.2, 13.2, 6.6 lean infrastructure).

resource "google_storage_bucket" "this" {
  for_each = var.buckets

  project                     = var.project_id
  name                        = "${var.project_id}-${each.key}"
  location                    = each.value.location
  uniform_bucket_level_access = true
  # No bucket may ever be made public, whatever IAM is later added (SEC-12).
  public_access_prevention = "enforced"
  force_destroy            = false

  versioning {
    enabled = each.value.versioning_enabled
  }

  dynamic "encryption" {
    for_each = each.value.kms_key_name != "" ? [each.value.kms_key_name] : []

    content {
      default_kms_key_name = encryption.value
    }
  }

  dynamic "lifecycle_rule" {
    for_each = each.value.lifecycle_rules

    content {
      action {
        type = lifecycle_rule.value.action_type
      }
      condition {
        age = lifecycle_rule.value.age_days
      }
    }
  }
}
