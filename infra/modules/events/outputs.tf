output "topic_name" {
  value = google_pubsub_topic.events.name
}

output "subscription_name" {
  description = "Name of the events -> BigQuery subscription (monitored for backlog)."
  value       = google_pubsub_subscription.events_to_bigquery.name
}

output "dataset_id" {
  value = google_bigquery_dataset.ledger.dataset_id
}

output "table_id" {
  value = google_bigquery_table.events.table_id
}

output "ledger_write_role" {
  description = "The custom insert-only role id granted to the Pub/Sub service agent (PRD 13.2 append-only)."
  # Built from project_id + role_id rather than the resource's computed
  # `id` attribute, so this stays known at plan time under mock providers.
  value = "projects/${var.project_id}/roles/${google_project_iam_custom_role.bq_ledger_inserter.role_id}"
}

output "pubsub_service_agent_email" {
  description = "Email of the Pub/Sub service agent."
  value       = google_project_service_identity.pubsub.email
}
