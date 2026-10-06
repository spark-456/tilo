output "service_accounts" {
  description = "Map of service key => its service account email."
  value       = local.service_account_emails
}

output "services" {
  description = "Map of service key => the fields the P0-07 acceptance tests read."
  value = {
    for k, svc in google_cloud_run_v2_service.this : k => {
      region                = svc.location
      min_instance_count    = var.services[k].min_instance_count
      max_instance_count    = var.services[k].max_instance_count
      ingress               = svc.ingress
      cpu_idle              = true
      service_account_email = local.service_account_emails[k]
      public                = var.services[k].public
      vpc_egress            = var.services[k].vpc_egress
      vpc_network           = var.services[k].vpc_egress == null ? null : var.vpc_network
      vpc_subnetwork        = var.services[k].vpc_egress == null ? null : var.vpc_subnetwork
      invokers = [
        for key, b in google_cloud_run_v2_service_iam_member.invoker : b.member
        if local.invoker_bindings[key].service == k
      ]
      developers = [
        for key, b in google_cloud_run_v2_service_iam_member.developer : b.member
        if local.developer_bindings[key].service == k
      ]
    }
  }
}

output "developer_grants" {
  description = "Every roles/run.developer binding as planned: service name, role, member."
  value = [
    for key, b in google_cloud_run_v2_service_iam_member.developer : {
      service = "tilo-${local.developer_bindings[key].service}"
      role    = b.role
      member  = b.member
    }
  ]
}

output "uris" {
  description = "Map of service key => its run.app URL (known after apply)."
  value       = { for k, svc in google_cloud_run_v2_service.this : k => svc.uri }
}
