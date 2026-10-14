# ACT-1 / FR-MEM-09: build before minutes activation; declarations only, the infra owner applies.
# All queries use the API's existing database. Single-field draft owner/expiry indexes are automatic.
locals {
  followup_retention_indexes = merge(
    {
      for group in ["cards", "stops"] : "${group}-owner" => {
        collection = group, scope = "COLLECTION_GROUP",
        fields     = ["org_id", "retention_namespace", "owner"]
      }
    },
    {
      for group in ["cards", "stops"] : "${group}-meeting" => {
        collection = group, scope = "COLLECTION_GROUP",
        fields     = ["org_id", "retention_namespace", "owner", "source.meeting_id"]
      }
    },
    {
      for group in ["cards", "stops"] : "${group}-expiry" => {
        collection = group, scope = "COLLECTION_GROUP",
        fields     = ["org_id", "retention_namespace", "expires_at"]
      }
    },
    {
      drafts-meeting = {
        collection = "followup_drafts", scope = "COLLECTION",
        fields     = ["owner", "source.meeting_id"]
      }
    }
  )
}

resource "google_firestore_index" "followup_retention" {
  for_each    = local.followup_retention_indexes
  project     = var.project_id
  database    = google_firestore_database.default.name
  collection  = each.value.collection
  query_scope = each.value.scope

  dynamic "fields" {
    for_each = each.value.fields
    content {
      field_path = fields.value
      order      = "ASCENDING"
    }
  }
}
