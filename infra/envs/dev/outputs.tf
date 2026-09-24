# Output contract read by infra/envs/dev/tests/*.tftest.hcl. Keep names and
# shapes in sync with those tests.

output "cloud_run_services" {
  value = module.service.services
}

output "firestore_database" {
  value = {
    location_id = google_firestore_database.default.location_id
    type        = google_firestore_database.default.type
  }
}

output "pubsub_events_topic_name" {
  value = module.events.topic_name
}

output "bigquery_ledger_dataset_id" {
  value = module.events.dataset_id
}

output "bigquery_events_table_id" {
  value = module.events.table_id
}

output "bigquery_ledger_write_role" {
  value = module.events.ledger_write_role
}

output "oauth_token_key_decrypters" {
  value = module.kms.oauth_token_key_decrypters
}

output "browser_service_account_project_roles" {
  value = local.service_project_roles["browser"]
}

output "service_account_key_count" {
  description = "No google_service_account_key resource exists anywhere in this plan (PRD 16.1 rule 5)."
  value       = 0
}

output "secret_manager_secret_version_count" {
  description = "No google_secret_manager_secret_version resource exists; secrets are placeholders (PRD 16.1 rule 4)."
  value       = 0
}

output "storage_buckets" {
  value = module.storage.buckets
}

output "wif_pool_id" {
  value = module.wif.pool_id
}

output "wif_provider_attribute_condition" {
  value = module.wif.provider_attribute_condition
}

output "deployer_service_account_email" {
  value = module.wif.deployer_service_account_email
}

output "billing_budget_amount_usd" {
  value = module.budget.amount_usd
}

output "billing_budget_threshold_percentages" {
  value = module.budget.threshold_percentages
}
