output "pool_id" {
  value = google_iam_workload_identity_pool.github.workload_identity_pool_id
}

output "provider_attribute_condition" {
  value = google_iam_workload_identity_pool_provider.github.attribute_condition
}

output "deployer_service_account_email" {
  # Built from account_id + project_id (fixed GCP convention) rather than
  # the resource's computed `email` attribute, so this stays known at plan
  # time under mock providers.
  value = "${google_service_account.deployer.account_id}@${var.project_id}.iam.gserviceaccount.com"
}
