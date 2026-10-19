# ACT-1 / FR-MEM-09: exact index fields for the called draft/card/stop cleanup queries.
mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  project_id                 = "tilo-dev-test"
  region                     = "asia-southeast1"
  billing_account_id         = "000000-000000-000000"
  github_repository          = "tilo-org/tilo"
  github_repository_id       = "123456789"
  github_repository_owner_id = "987654321"
  budget_amount_usd          = 150
  alert_email                = "alerts@example.com"
}

run "ACT_1_FR_MEM_09_retention_query_indexes" {
  command = plan

  assert {
    condition = toset(keys(google_firestore_index.followup_retention)) == toset([
      "cards-owner", "cards-meeting", "cards-expiry",
      "stops-owner", "stops-meeting", "stops-expiry", "drafts-meeting"
    ])
    error_message = "Every owner, source-meeting and expiry group query requires an index."
  }

  assert {
    condition = alltrue([for key, index in google_firestore_index.followup_retention :
      index.database == google_firestore_database.default.name &&
      index.collection == (key == "drafts-meeting" ? "followup_drafts" : split("-", key)[0]) &&
      index.query_scope == (key == "drafts-meeting" ? "COLLECTION" : "COLLECTION_GROUP") &&
      tolist([for field in index.fields : "${field.field_path}:${field.order}"]) == tolist(
        key == "drafts-meeting" ? ["owner:ASCENDING", "source.meeting_id:ASCENDING"] : concat(
          ["org_id:ASCENDING", "retention_namespace:ASCENDING"],
          endswith(key, "-expiry") ? ["expires_at:ASCENDING"] : (
            endswith(key, "-meeting") ? ["owner:ASCENDING", "source.meeting_id:ASCENDING"] : ["owner:ASCENDING"]
          )
        )
      )
    ])
    error_message = "Cleanup indexes must bind the org/namespace, query scope, and exact owner/source/expiry fields."
  }
}
