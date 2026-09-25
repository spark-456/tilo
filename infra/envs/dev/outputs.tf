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
  value = [
    for b in values(module.iam.bindings) : b.role
    if b.member == "serviceAccount:${module.service.service_accounts["browser"]}"
  ]
}

output "project_iam_bindings" {
  description = "Every project-level binding (role, member) in the plan."
  value       = values(module.iam.bindings)
}

output "events_topic_publishers" {
  description = "Members granted roles/pubsub.publisher on tilo-events."
  value       = [for b in google_pubsub_topic_iam_member.events_publishers : b.member]
}

output "secret_accessors" {
  description = "secret id => members granted secretAccessor on it."
  value = {
    for s in local.secret_placeholders : s => [
      for b in google_secret_manager_secret_iam_member.accessors : b.member if b.secret_id == s
    ]
  }
}

output "deployer_act_as_service_accounts" {
  description = "Service accounts the WIF deployer may act as."
  value       = [for b in google_service_account_iam_member.deployer_act_as : b.service_account_id]
}

# Counted from the HCL source of every module under infra/, so a key or
# secret version added anywhere makes these non-zero (PRD 16.1 rules 4, 5).
locals {
  infra_root    = "${path.module}/../.."
  infra_sources = [for f in fileset(local.infra_root, "**/*.tf") : file("${local.infra_root}/${f}")]
}

output "service_account_key_count" {
  description = "google_service_account_key resources declared anywhere under infra/ (PRD 16.1 rule 5)."
  value       = sum([for s in local.infra_sources : length(regexall("resource\\s+\"google_service_account_key\"", s))])
}

output "secret_manager_secret_version_count" {
  description = "google_secret_manager_secret_version resources declared anywhere under infra/ (PRD 16.1 rule 4)."
  value       = sum([for s in local.infra_sources : length(regexall("resource\\s+\"google_secret_manager_secret_version\"", s))])
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

output "vpc_egress_subnetwork" {
  value = {
    name                     = google_compute_subnetwork.run_egress.name
    network                  = google_compute_network.vpc.name
    region                   = google_compute_subnetwork.run_egress.region
    private_ip_google_access = google_compute_subnetwork.run_egress.private_ip_google_access
  }
}
