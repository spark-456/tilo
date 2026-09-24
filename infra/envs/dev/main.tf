# tilo-dev environment: composes infra/modules/* to satisfy the P0-07
# acceptance tests (infra/envs/dev/tests/*.tftest.hcl). See infra/README.md
# for the commands the user runs to apply this plan.

data "google_project" "current" {
  project_id = var.project_id
}

locals {
  project_number = data.google_project.current.number

  required_apis = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "firestore.googleapis.com",
    "pubsub.googleapis.com",
    "bigquery.googleapis.com",
    "storage.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudtasks.googleapis.com",
    "cloudbilling.googleapis.com",
    "billingbudgets.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "firebase.googleapis.com",
    "firebasehosting.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
  ])

  # Public placeholder image until CI deploys real images per service.
  placeholder_image = "us-docker.pkg.dev/cloudrun/container/hello"

  # PRD 6.2 services, 6.5 ingress rule: public only for api, channels
  # (webhooks) and sandbox-web; everything else internal only.
  cloud_run_services = {
    "api" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 3
      ingress            = "INGRESS_TRAFFIC_ALL"
    }
    "harness" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 3
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
    }
    "channels" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 3
      ingress            = "INGRESS_TRAFFIC_ALL"
    }
    "connectors" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
    }
    "browser" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
    }
    "render" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
    }
    "sandbox-web" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_ALL"
    }
  }

  # Project-level roles per service (PRD 6.5 one least-privilege SA per
  # service; SEC-12: tilo-browser holds no Firestore/Datastore or Storage
  # role). KMS decrypt access is scoped to the oauth-tokens key itself, not
  # granted here (see module.kms).
  service_project_roles = {
    "api"         = ["roles/datastore.user", "roles/pubsub.publisher", "roles/cloudtasks.enqueuer"]
    "harness"     = ["roles/datastore.user", "roles/pubsub.publisher", "roles/cloudtasks.enqueuer", "roles/aiplatform.user"]
    "channels"    = ["roles/datastore.user", "roles/pubsub.publisher"]
    "connectors"  = ["roles/datastore.user", "roles/secretmanager.secretAccessor"]
    "browser"     = []
    "render"      = ["roles/datastore.user", "roles/storage.objectAdmin"]
    "sandbox-web" = []
  }

  deployer_project_roles = [
    "roles/run.admin",
    "roles/artifactregistry.writer",
    "roles/iam.serviceAccountUser",
  ]

  # Keyed statically (service/role names, never a computed attribute) so
  # terraform test can plan module.iam against mock providers.
  project_bindings = merge(
    { for combo in flatten([
      for name, roles in local.service_project_roles : [
        for role in roles : {
          key    = "${name}::${role}"
          role   = role
          member = "serviceAccount:${module.service.service_accounts[name]}"
        }
      ]
      ]) : combo.key => { role = combo.role, member = combo.member }
    },
    { for role in local.deployer_project_roles :
      "deployer::${role}" => {
        role   = role
        member = "serviceAccount:${module.wif.deployer_service_account_email}"
      }
    }
  )

  # Secret Manager placeholders: names only. Values are added by the user
  # out of band, never in Terraform (PRD 16.1 rule 4).
  secret_placeholders = toset([
    "workspace-oauth-client",
    "whatsapp-api-token",
    "channels-webhook-signing-key",
    "email-action-link-signing-key",
  ])
}

resource "google_project_service" "apis" {
  for_each = local.required_apis

  project                    = var.project_id
  service                    = each.value
  disable_dependent_services = false
  disable_on_destroy         = false
}

# ---------------------------------------------------------------------------
# Cloud Run services (PRD 6.2) and their service accounts.
# ---------------------------------------------------------------------------

module "service" {
  source = "../../modules/service"

  project_id = var.project_id
  region     = var.region
  services   = local.cloud_run_services

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Identity: Workload Identity Federation for CI, project IAM bindings.
# ---------------------------------------------------------------------------

module "wif" {
  source = "../../modules/wif"

  project_id        = var.project_id
  github_repository = var.github_repository

  depends_on = [google_project_service.apis]
}

module "iam" {
  source = "../../modules/iam"

  project_id = var.project_id
  bindings   = local.project_bindings
}

# ---------------------------------------------------------------------------
# Cloud KMS: oauth-tokens (connectors-only decrypt) and archive keys.
# ---------------------------------------------------------------------------

module "kms" {
  source = "../../modules/kms"

  project_id = var.project_id
  region     = var.region

  oauth_token_decrypters = {
    connectors = "serviceAccount:${module.service.service_accounts["connectors"]}"
  }

  archive_key_principals = {
    connectors = "serviceAccount:${module.service.service_accounts["connectors"]}"
    harness    = "serviceAccount:${module.service.service_accounts["harness"]}"
    # Cloud Storage's own service agent must be able to use the archive key
    # to encrypt/decrypt objects in the CMEK-encrypted archive bucket.
    gcs_agent = "serviceAccount:service-${local.project_number}@gs-project-accounts.iam.gserviceaccount.com"
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Cloud Storage: artifacts (versioned), archive (CMEK, 30-day delete),
# snapshots (PRD 6.2, 13.2).
# ---------------------------------------------------------------------------

module "storage" {
  source = "../../modules/storage"

  project_id = var.project_id

  buckets = {
    "artifacts" = {
      location           = var.region
      versioning_enabled = true
      kms_key_name       = ""
      lifecycle_rules = [
        { action_type = "Delete", age_days = 365 },
      ]
    }
    "archive" = {
      location           = var.region
      versioning_enabled = false
      kms_key_name       = module.kms.archive_key_id
      lifecycle_rules = [
        { action_type = "Delete", age_days = 30 },
      ]
    }
    "snapshots" = {
      location           = var.region
      versioning_enabled = false
      kms_key_name       = ""
      lifecycle_rules = [
        { action_type = "Delete", age_days = 90 },
      ]
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Firestore (native mode, PRD 15.3), events topic and BigQuery ledger
# (PRD 13.2), Cloud Tasks, Artifact Registry, Secret Manager placeholders,
# Firebase Hosting for the web client (PRD 6.2, 6.3).
# ---------------------------------------------------------------------------

resource "google_firestore_database" "default" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.apis]
}

module "events" {
  source = "../../modules/events"

  project_id     = var.project_id
  project_number = local.project_number
  region         = var.region

  depends_on = [google_project_service.apis]
}

resource "google_cloud_tasks_queue" "runs" {
  project  = var.project_id
  name     = "runs"
  location = var.region

  depends_on = [google_project_service.apis]
}

resource "google_artifact_registry_repository" "containers" {
  project       = var.project_id
  location      = var.region
  repository_id = "tilo"
  format        = "DOCKER"
  description   = "Tilo service container images (PRD 6.3 Cloud Build, Artifact Registry)."

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "placeholders" {
  for_each = local.secret_placeholders

  project   = var.project_id
  secret_id = each.value

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }

  depends_on = [google_project_service.apis]
}

resource "google_firebase_project" "default" {
  provider = google-beta
  project  = var.project_id

  depends_on = [google_project_service.apis]
}

resource "google_firebase_hosting_site" "web" {
  provider = google-beta
  project  = var.project_id
  site_id  = "${var.project_id}-web"

  depends_on = [google_firebase_project.default]
}

# ---------------------------------------------------------------------------
# Billing budget (PRD 17.3).
# ---------------------------------------------------------------------------

module "budget" {
  source = "../../modules/budget"

  billing_account_id    = var.billing_account_id
  project_number        = local.project_number
  display_name          = "tilo-${var.project_id}-monthly"
  amount_usd            = var.budget_amount_usd
  threshold_percentages = [0.5, 0.9, 1.0]
}
