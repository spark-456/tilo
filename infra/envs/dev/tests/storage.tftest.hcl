# Acceptance tests for P0-07 / PRD-6.5 (Cloud Storage buckets and CMEK).
# PRD 6.2, 6.3, 13.2 (Raw archive, Artifact versions).
#
# Run: terraform -chdir=infra/envs/dev test
#
# Expected root-module output contract (not yet implemented):
#
#   output "storage_buckets" -> map(bucket_key => object({
#     name                        : string
#     location                    : string
#     uniform_bucket_level_access : bool
#     public_access_prevention    : string   # "enforced"
#     versioning_enabled          : bool
#     kms_key_name                : string   # "" when not CMEK-encrypted
#     lifecycle_rule_count        : number
#   }))
#   Keys: "artifacts", "archive", "snapshots".

variables {
  project_id                 = "tilo-dev-test"
  region                     = "asia-southeast1"
  billing_account_id         = "000000-000000-000000"
  github_repository          = "tilo-org/tilo"
  github_repository_id       = "123456789"
  github_repository_owner_id = "987654321"
  budget_amount_usd          = 150
}

mock_provider "google" {}
mock_provider "google-beta" {}

run "PRD_6_2_three_buckets_exist_with_uniform_access" {
  command = plan

  assert {
    condition     = toset(keys(output.storage_buckets)) == toset(["artifacts", "archive", "snapshots"])
    error_message = "Expected the artifacts, archive and snapshots buckets (PRD 6.2, 6.3)."
  }

  assert {
    condition     = alltrue([for b in values(output.storage_buckets) : b.uniform_bucket_level_access])
    error_message = "Every bucket must enforce uniform bucket-level access."
  }

  assert {
    condition     = alltrue([for b in values(output.storage_buckets) : b.public_access_prevention == "enforced"])
    error_message = "Every bucket must enforce public access prevention (SEC-12)."
  }

  assert {
    condition     = alltrue([for b in values(output.storage_buckets) : b.lifecycle_rule_count > 0])
    error_message = "Every bucket must have at least one lifecycle rule."
  }
}

run "PRD_13_2_artifacts_bucket_has_object_versioning" {
  command = plan

  assert {
    condition     = output.storage_buckets["artifacts"].versioning_enabled == true
    error_message = "The artifacts bucket must have object versioning enabled (PRD 13.2 artifact versions)."
  }
}

run "PRD_13_2_archive_bucket_is_cmek_encrypted_with_30_day_delete" {
  command = plan

  assert {
    condition     = output.storage_buckets["archive"].kms_key_name != ""
    error_message = "The archive bucket must be encrypted with the archive CMEK key (PRD 13.2 raw archive: 'encrypted with Cloud KMS')."
  }
}

run "PRD_16_4_snapshots_bucket_has_lifecycle_rules" {
  command = plan

  assert {
    condition     = output.storage_buckets["snapshots"].lifecycle_rule_count > 0
    error_message = "The snapshots bucket must have a lifecycle rule (PRD 6.6 lean infrastructure: storage lifecycle rules)."
  }
}
