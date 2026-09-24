# Reusable piece: one least-privilege service account plus one Cloud Run v2
# service per entry in var.services (PRD 6.2 services, 6.5 environments).
# No project-level IAM roles are granted here -- see modules/iam, composed by
# the environment root so all project bindings are visible in one place.
#
# Service account emails are built from account_id + project_id rather than
# read off the resource's computed `email` attribute: the format is a fixed
# GCP convention, and building it this way keeps the value known at plan
# time (required for `terraform test` to assert on it against mock
# providers, PRD 6.5 one SA per service).

locals {
  service_account_emails = {
    for k, _ in var.services : k => "tilo-${k}@${var.project_id}.iam.gserviceaccount.com"
  }
}

resource "google_service_account" "this" {
  for_each = var.services

  project      = var.project_id
  account_id   = "tilo-${each.key}"
  display_name = "Tilo ${each.key} service (PRD 6.2)"
}

resource "google_cloud_run_v2_service" "this" {
  for_each = var.services

  project             = var.project_id
  name                = "tilo-${each.key}"
  location            = var.region
  deletion_protection = false
  ingress             = each.value.ingress

  # Depends on the service accounts existing even though the field below is
  # a constructed string, not a resource attribute reference.
  depends_on = [google_service_account.this]

  template {
    service_account = local.service_account_emails[each.key]

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
}
