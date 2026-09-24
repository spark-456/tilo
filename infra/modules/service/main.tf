# Reusable piece: one least-privilege service account plus one Cloud Run v2
# service per entry in var.services (PRD 6.2 services, 6.5 environments).
# No project-level IAM roles are granted here -- see modules/iam, composed by
# the environment root so all project bindings are visible in one place.
#
# Service account emails are built from the google_service_account.this
# resource's own account_id and project attributes (fixed GCP convention)
# rather than its computed `email`: this keeps the value known at plan time
# (so `terraform test` can assert on it against mock providers) while still
# being a reference to the resource, so every consumer of the emails -- here
# and through outputs.service_accounts in the environment root -- waits
# until the service account exists before granting it anything.

resource "google_service_account" "this" {
  for_each = var.services

  project      = var.project_id
  account_id   = "tilo-${each.key}"
  display_name = "Tilo ${each.key} service (PRD 6.2)"
}

locals {
  service_account_emails = {
    for k, sa in google_service_account.this : k => "${sa.account_id}@${sa.project}.iam.gserviceaccount.com"
  }
}

resource "google_cloud_run_v2_service" "this" {
  for_each = var.services

  project             = var.project_id
  name                = "tilo-${each.key}"
  location            = var.region
  deletion_protection = false
  ingress             = each.value.ingress

  template {
    service_account = local.service_account_emails[each.key]

    # Direct VPC egress for callers of internal-only services (PRD 6.1):
    # a Cloud Run service that calls another over the public internet is
    # rejected by INGRESS_TRAFFIC_INTERNAL_ONLY; traffic leaving through the
    # VPC subnet (Private Google Access on) counts as internal.
    dynamic "vpc_access" {
      for_each = each.value.vpc_egress == null ? [] : [each.value.vpc_egress]
      content {
        egress = vpc_access.value
        network_interfaces {
          network    = var.vpc_network
          subnetwork = var.vpc_subnetwork
        }
      }
    }

    scaling {
      min_instance_count = each.value.min_instance_count
      max_instance_count = each.value.max_instance_count
    }

    containers {
      image = each.value.image

      resources {
        # Request-based CPU billing: CPU is only allocated while a request
        # is being processed (PRD 6.6 lean infrastructure).
        cpu_idle = true

        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  # CI deploys real images (PRD 6.5); a later plan must not roll services
  # back to the placeholder image.
  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

locals {
  # Static keys "<service>::<invoker>" so for_each is known at plan time.
  invoker_bindings = merge(
    { for k, v in var.services : "${k}::allUsers" => { service = k, member = "allUsers" } if v.public },
    { for combo in flatten([
      for k, v in var.services : [
        for caller in v.invoked_by : {
          key     = "${k}::${caller}"
          service = k
          member  = "serviceAccount:${local.service_account_emails[caller]}"
        }
      ]
      ]) : combo.key => { service = combo.service, member = combo.member }
    },
    var.extra_invokers,
  )
}

# Ingress only opens the network path; run.invoker decides who may call.
# Public services get allUsers (they verify webhook signatures or Firebase
# ID tokens themselves, SEC-08, FR-CHN-02); internal services get only
# their real callers (PRD 6.1).
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  for_each = local.invoker_bindings

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this[each.value.service].name
  role     = "roles/run.invoker"
  member   = each.value.member

  depends_on = [google_service_account.this]
}

locals {
  # Static keys "<service>::<developer key>" so for_each is known at plan time.
  developer_bindings = { for combo in setproduct(keys(var.services), keys(var.developers)) :
    "${combo[0]}::${combo[1]}" => { service = combo[0], member = var.developers[combo[1]] }
  }
}

# CI deploys revisions to these services only: roles/run.developer is
# granted per service, never project-wide, so the deployer cannot touch any
# other Cloud Run service in the project. run.developer cannot set IAM, so
# invoker bindings stay owned by Terraform (above).
resource "google_cloud_run_v2_service_iam_member" "developer" {
  for_each = local.developer_bindings

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this[each.value.service].name
  role     = "roles/run.developer"
  member   = each.value.member
}
