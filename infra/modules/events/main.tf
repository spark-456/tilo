# Reusable piece: the tilo-events topic and its append-only BigQuery ledger
# (PRD 6.2, 6.3, 13.2 event ledger, 15.3). The Pub/Sub BigQuery subscription
# writes directly; its service agent is granted a custom insert-only role
# instead of a broad dataEditor/dataOwner role, so the ledger stays
# append-only (PRD 13.2: "Deduplicated by id").

resource "google_pubsub_topic" "events" {
  project = var.project_id
  name    = "tilo-events"
}

resource "google_bigquery_dataset" "ledger" {
  project    = var.project_id
  dataset_id = "tilo_ledger"
  location   = var.region
}

resource "google_bigquery_table" "events" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.ledger.dataset_id
  table_id            = "events"
  deletion_protection = false

  # Top-level TiloEvent v1 fields (PRD 9.3). Nested payloads (item, vis,
  # authz, data, trace) are stored as JSON: their shape is defined per event
  # type in contracts/events/registry.yaml, not fixed BigQuery columns.
  schema = jsonencode([
    { name = "v", type = "STRING", mode = "REQUIRED" },
    { name = "id", type = "STRING", mode = "REQUIRED" },
    { name = "seq", type = "INTEGER", mode = "REQUIRED" },
    { name = "ts", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "world_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_id", type = "STRING", mode = "NULLABLE" },
    { name = "type", type = "STRING", mode = "REQUIRED" },
    { name = "actor", type = "STRING", mode = "NULLABLE" },
    { name = "target", type = "STRING", mode = "NULLABLE" },
    { name = "level", type = "STRING", mode = "NULLABLE" },
    { name = "district", type = "STRING", mode = "NULLABLE" },
    { name = "item", type = "JSON", mode = "NULLABLE" },
    { name = "severity", type = "STRING", mode = "REQUIRED" },
    { name = "credits", type = "FLOAT", mode = "NULLABLE" },
    { name = "summary", type = "STRING", mode = "NULLABLE" },
    { name = "cause", type = "STRING", mode = "NULLABLE" },
    { name = "vis", type = "JSON", mode = "NULLABLE" },
    { name = "authz", type = "JSON", mode = "NULLABLE" },
    { name = "data", type = "JSON", mode = "NULLABLE" },
    { name = "trace", type = "JSON", mode = "NULLABLE" },
  ])
}

resource "google_project_iam_custom_role" "bq_ledger_inserter" {
  project     = var.project_id
  role_id     = "tiloBqLedgerInserter"
  title       = "Tilo BigQuery ledger inserter"
  description = "Insert-only access for the Pub/Sub subscription that streams events into the append-only ledger (PRD 13.2)."
  permissions = [
    "bigquery.tables.get",
    "bigquery.tables.updateData",
  ]
}

locals {
  pubsub_service_agent = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_bigquery_dataset_iam_member" "ledger_insert_only" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.ledger.dataset_id
  role       = google_project_iam_custom_role.bq_ledger_inserter.id
  member     = local.pubsub_service_agent
}

resource "google_pubsub_subscription" "events_to_bigquery" {
  project = var.project_id
  name    = "tilo-events-to-bigquery"
  topic   = google_pubsub_topic.events.id

  bigquery_config {
    table            = "${var.project_id}.${google_bigquery_dataset.ledger.dataset_id}.${google_bigquery_table.events.table_id}"
    use_table_schema = true
  }

  depends_on = [google_bigquery_dataset_iam_member.ledger_insert_only]
}
