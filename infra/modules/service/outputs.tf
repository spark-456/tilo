output "service_accounts" {
  description = "Map of service key => its service account email."
  value       = local.service_account_emails
}

output "services" {
  description = "Map of service key => the fields the P0-07 acceptance tests read."
  value = {
    for k, svc in local.run_services : k => {
      region                = svc.location
      cpu                   = svc.template[0].containers[0].resources[0].limits["cpu"]
      memory                = svc.template[0].containers[0].resources[0].limits["memory"]
      timeout               = svc.template[0].timeout
      request_concurrency   = svc.template[0].max_instance_request_concurrency
      min_instance_count    = var.services[k].min_instance_count
      max_instance_count    = var.services[k].max_instance_count
      ingress               = svc.ingress
      cpu_idle              = var.services[k].cpu_idle
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
  value       = { for k, svc in local.run_services : k => svc.uri }
}
