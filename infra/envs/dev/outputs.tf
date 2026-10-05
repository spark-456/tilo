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
  # Built from the config map (not b.secret_id, which the API returns as a
  # full resource path after refresh), so it is the same before and after.
  value = {
    for s, services in local.secret_accessors : s => [
      for svc in services : google_secret_manager_secret_iam_member.accessors["${s}::${svc}"].member
    ]
  }
}

output "monitoring" {
  description = "Alert email and alert policies (config values)."
  value = {
    notification_email = module.monitoring.notification_channel_email
    alert_policies     = module.monitoring.alert_policies
    cost_alert_policy  = module.monitoring.cost_alert_policy
  }
}

output "enabled_apis" {
  description = "Service APIs this environment enables (adopts if already enabled)."
  value       = sort(keys(google_project_service.apis))
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

output "oauth_token_key_role" {
  description = "The single role bound on the oauth-tokens key (connectors only)."
  value       = module.kms.oauth_token_key_role
}

output "gmail_push" {
  description = "Gmail push topic, subscription path and Scheduler jobs (FR-CHN-08)."
  value = {
    topic_name        = module.gmail_push.topic_name
    topic_publishers  = module.gmail_push.topic_publishers
    subscription_name = module.gmail_push.subscription_name
    push_path         = module.gmail_push.push_path
    scheduler_jobs    = module.gmail_push.scheduler_jobs
  }
}

output "service_storage_grants" {
  description = "bucket::service::role => member for the bucket-scoped service grants (PRD 13.2)."
  value       = { for k, b in google_storage_bucket_iam_member.service_access : k => b.member }
}

output "model_armor_template" {
  value = {
    location    = google_model_armor_template.default.location
    template_id = google_model_armor_template.default.template_id
  }
}

# Cloud Build identity (P0-07g, cloudbuild.tftest.hcl): its email, the one
# list of every binding it holds (derived from the real IAM resources), the
# runtime accounts it may act as and the source staging bucket.
output "cloudbuild_service_account_email" {
  # Built from the account id (the resource's computed email is unknown at plan time).
  value = local.cloudbuild_service_account_email
}

output "cloudbuild_grants" {
  description = "Every binding tilo-cloudbuild holds: scope, resource, role."
  value = concat(
    [{
      scope    = "artifact_registry_repository"
      resource = google_artifact_registry_repository_iam_member.cloudbuild_writer.repository
      role     = google_artifact_registry_repository_iam_member.cloudbuild_writer.role
    }],
    [for g in module.service.developer_grants : {
      scope    = "cloud_run_service"
      resource = g.service
      role     = g.role
    } if g.member == "serviceAccount:${local.cloudbuild_service_account_email}"],
    [for k, b in google_service_account_iam_member.cloudbuild_act_as : {
      scope    = "service_account"
      resource = module.service.service_accounts[k]
      role     = b.role
    }],
    [for b in values(module.iam.bindings) : {
      scope    = "project"
      resource = var.project_id
      role     = b.role
    } if b.member == "serviceAccount:${local.cloudbuild_service_account_email}"],
    [{
      scope    = "storage_bucket"
      resource = google_storage_bucket_iam_member.cloudbuild_staging_viewer.bucket
      role     = google_storage_bucket_iam_member.cloudbuild_staging_viewer.role
    }],
  )
}

output "cloudbuild_act_as_service_accounts" {
  description = "Service accounts tilo-cloudbuild may act as."
  value       = [for b in google_service_account_iam_member.cloudbuild_act_as : b.service_account_id]
}

output "cloudbuild_staging_bucket" {
  description = "The Terraform-managed source staging bucket (not one of storage_buckets)."
  value = {
    name                        = module.storage_cloudbuild_staging.buckets["cloudbuild-staging"].name
    location                    = module.storage_cloudbuild_staging.buckets["cloudbuild-staging"].location
    uniform_bucket_level_access = module.storage_cloudbuild_staging.buckets["cloudbuild-staging"].uniform_bucket_level_access
    public_access_prevention    = module.storage_cloudbuild_staging.buckets["cloudbuild-staging"].public_access_prevention
    lifecycle_rules             = module.storage_cloudbuild_staging.lifecycle_rules["cloudbuild-staging"]
  }
}
