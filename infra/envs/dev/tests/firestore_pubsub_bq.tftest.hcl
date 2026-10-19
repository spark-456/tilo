# Acceptance tests for P0-07 / PRD-6.5 (Firestore, Pub/Sub, BigQuery ledger).
# PRD 6.2, 6.3, 13.2 (Event ledger), 15.3 (Firestore layout).
#
# Run: terraform -chdir=infra/envs/dev test
#
# Expected root-module output contract (not yet implemented):
#
#   output "firestore_database" -> object({ location_id: string, type: string })
#   output "pubsub_events_topic_name" -> string
#   output "bigquery_ledger_dataset_id" -> string
#   output "bigquery_events_table_id" -> string
#   output "bigquery_ledger_write_role" -> string
#     IAM role granted to the Pub/Sub subscription's service agent on the
#     events table. Must be a data-insert-only role, never the broad
#     dataEditor/dataOwner roles, so the ledger stays append-only.

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

mock_provider "google" {}
mock_provider "google-beta" {}

run "PRD_6_3_firestore_native_database_in_region" {
  command = plan

  assert {
    condition     = output.firestore_database.location_id == var.region
    error_message = "Firestore database must be in asia-southeast1 (PRD 6.5 region rule)."
  }

  assert {
    condition     = output.firestore_database.type == "FIRESTORE_NATIVE"
    error_message = "Firestore must run in Native mode (PRD 15.3)."
  }
}

run "PRD_6_2_events_topic_and_bigquery_ledger_exist" {
  command = plan

  assert {
    condition     = output.pubsub_events_topic_name == "tilo-events"
    error_message = "The events topic must be named tilo-events (PRD 6.2)."
  }

  assert {
    condition     = output.bigquery_ledger_dataset_id == "tilo_ledger"
    error_message = "The ledger dataset must be tilo_ledger (PRD 13.2 event ledger)."
  }

  assert {
    condition     = output.bigquery_events_table_id == "events"
    error_message = "The ledger table must be named events (PRD 13.2)."
  }
}

run "PRD_13_2_ledger_is_append_only_via_insert_only_grant" {
  command = plan

  assert {
    condition = !contains(
      ["roles/bigquery.dataEditor", "roles/bigquery.dataOwner", "roles/editor", "roles/owner"],
      output.bigquery_ledger_write_role
    )
    error_message = "The BigQuery subscription's service agent must be granted an insert-only role, never a broad editor/owner role, so the event ledger stays append-only (PRD 13.2: 'Deduplicated by id', append-only)."
  }
}

# ADR-0035 decision 9 (L7): the durable outbox's pending-transfer query (`transfer_pending == true ORDER BY enqueued_at`,
# tilo_api.outbox_firestore) needs this composite index in the (default) database. It must be built before
# TILO_OUTBOX_STORE=firestore is set: without it claiming a transfer raises 503 after a sent entry (PI-17). The alert
# query is one equality filter on `alert_pending` and needs none.
run "ADR35_L7_the_outbox_pending_transfer_query_has_its_composite_index" {
  command = plan

  assert {
    condition     = google_firestore_index.outbox_transfer_pending.collection == "outbox" && google_firestore_index.outbox_transfer_pending.query_scope == "COLLECTION"
    error_message = "A COLLECTION-scoped composite index on the `outbox` collection."
  }

  assert {
    condition = [for f in google_firestore_index.outbox_transfer_pending.fields : "${f.field_path}:${f.order}"] == [
      "transfer_pending:ASCENDING",
      "enqueued_at:ASCENDING",
    ]
    error_message = "The index fields are transfer_pending ASC, enqueued_at ASC, in that order."
  }

  assert {
    condition     = google_firestore_index.outbox_transfer_pending.database == google_firestore_database.default.name
    error_message = "The index is in the (default) database, where tilo-api's outbox lives (never tilo-tokens)."
  }
}
