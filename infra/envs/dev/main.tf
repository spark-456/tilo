# tilo-dev environment: composes infra/modules/* to satisfy the P0-07
# acceptance tests (infra/envs/dev/tests/*.tftest.hcl). See infra/README.md
# for the commands the user runs to apply this plan.

data "google_project" "current" {
  project_id = var.project_id
}

# The Cloud Storage service agent is provisioned on demand; reading it here
# (rather than constructing its email from the project number) makes sure it
# actually exists before module.kms grants it a role, so that grant cannot
# silently fail on a fresh project.
data "google_storage_project_service_account" "gcs" {
  project = var.project_id
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
    "compute.googleapis.com",
    # PRD 6.3 services (P0-07b). The three Workspace APIs were enabled by
    # hand first; listing them here adopts them (a no-op apply).
    "modelarmor.googleapis.com",
    "cloudscheduler.googleapis.com",
    "identitytoolkit.googleapis.com",
    "firebaseappcheck.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "logging.googleapis.com",
    "gmail.googleapis.com",
    "calendar-json.googleapis.com",
    "drive.googleapis.com",
    # Access audit (infra/ACCESS.md): enabled here so nothing is enabled by
    # hand later. No image, video or speech APIs: no profile names one.
    "serviceusage.googleapis.com",
    "firebaserules.googleapis.com",
    "recaptchaenterprise.googleapis.com",
    "docs.googleapis.com",
    "sheets.googleapis.com",
    "slides.googleapis.com",
    "bigquerystorage.googleapis.com",
  ])

  # ALL_TRAFFIC: every request from api and harness leaves through the VPC
  # subnet, so calls to internal-only services pass the ingress check and
  # Google APIs are reached via Private Google Access (network.tf). There is
  # no Cloud NAT, so these two services have no public-internet egress;
  # third-party calls belong in connectors or channels (PRD 6.1).
  caller_vpc_egress = "ALL_TRAFFIC"

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
      public             = true
      invoked_by         = []
      vpc_egress         = local.caller_vpc_egress # calls harness directly
    }
    "harness" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 3
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      public             = false
      # PRD 6.1: API --> Cloud Tasks --> harness. The Cloud Tasks OIDC
      # identity is granted below via extra_invokers.
      invoked_by = ["api"]
      # Calls connectors, browser and render (all internal-only).
      vpc_egress = local.caller_vpc_egress
    }
    "channels" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 3
      ingress            = "INGRESS_TRAFFIC_ALL"
      public             = true
      invoked_by         = []
    }
    "connectors" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      public             = false
      invoked_by         = ["harness"] # PRD 6.1: harness --> connectors
    }
    "browser" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      public             = false
      invoked_by         = ["harness"] # PRD 6.1: harness --> browser
    }
    "render" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      public             = false
      invoked_by         = ["harness"] # PRD 6.1: harness --> render
    }
    "sandbox-web" = {
      image              = local.placeholder_image
      min_instance_count = 0
      max_instance_count = 2
      ingress            = "INGRESS_TRAFFIC_ALL"
      public             = true
      invoked_by         = []
    }
  }

  # Project-level roles per service (PRD 6.5 one least-privilege SA per
  # service; SEC-12: tilo-browser holds no Firestore/Datastore or Storage
  # role). KMS decrypt access is scoped to the oauth-tokens key itself, not
  # granted here (see module.kms). Cloud Storage access is bucket-scoped,
  # not project-wide (see the google_storage_bucket_iam_member grants below
  # module.storage): a project-level storage role would reach every bucket
  # in the project, including the CMEK archive bucket and the Terraform
  # state bucket, not just the bucket a given service actually needs.
  # Pub/Sub publish is granted on the tilo-events topic to harness only
  # (PRD 15.3: harness is the only event writer), and Secret Manager access
  # per secret (secret_accessors below), never project-wide. tilo-channels
  # is internet-facing and writes only through the API (PRD 6.1), so it holds
  # no data role; it only calls models (triage, drafting) and the safety
  # provider. aiplatform.user and modelarmor.user cannot be scoped below the
  # project (no resource-level IAM for publisher models or Model Armor
  # templates); they go to exactly the services whose code calls the
  # provider layer (api Router and intake screen, harness, channels).
  service_project_roles = {
    "api"         = ["roles/datastore.user", "roles/cloudtasks.enqueuer", "roles/aiplatform.user", "roles/modelarmor.user"]
    "harness"     = ["roles/datastore.user", "roles/cloudtasks.enqueuer", "roles/aiplatform.user", "roles/modelarmor.user"]
    "channels"    = ["roles/aiplatform.user", "roles/modelarmor.user"]
    "connectors"  = ["roles/datastore.user"]
    "browser"     = []
    "render"      = ["roles/datastore.user"]
    "sandbox-web" = []
  }

  # secret => services allowed roles/secretmanager.secretAccessor on it.
  secret_accessors = {
    "workspace-oauth-client"        = ["connectors"]
    "whatsapp-api-token"            = ["channels"]
    "channels-webhook-signing-key"  = ["channels"]
    "email-action-link-signing-key" = ["api", "channels"] # channels signs/verifies links (links.py)
    # Slots the PRD implies (names only; values are added by the user).
    "whatsapp-webhook-verify-token" = ["channels"] # Meta GET handshake (FR-CHN-02)
    "channel-binding-hmac-key"      = ["channels"] # binding.py HMAC (FR-CHN-03, SEC-06)
    "channel-number-encryption-key" = ["channels"] # binding.py number cipher (FR-CHN-03)
    "webpush-vapid-private-key"     = ["channels"] # web push (FR-CHN-17)
  }
  secret_accessor_bindings = { for combo in flatten([
    for secret, services in local.secret_accessors : [
      for svc in services : { key = "${secret}::${svc}", secret = secret, svc = svc }
    ]
  ]) : combo.key => combo }

  # Keyed statically (service/role names, never a computed attribute) so
  # terraform test can plan module.iam against mock providers.
  # The WIF deployer holds no project role: run.developer is granted on the
  # seven services (module.service developers), serviceAccountUser per
  # runtime SA and Artifact Registry write on the tilo repository (below).
  project_bindings = merge({ for combo in flatten([
    for name, roles in local.service_project_roles : [
      for role in roles : {
        key    = "${name}::${role}"
        role   = role
        member = "serviceAccount:${module.service.service_accounts[name]}"
      }
    ]
    ]) : combo.key => { role = combo.role, member = combo.member }
    },
    { for r in var.deployer_project_roles : "deployer::${r}" => {
      role = r, member = "serviceAccount:${module.wif.deployer_service_account_email}"
    } },
  )

  # Secret Manager placeholders: names only. Values are added by the user
  # out of band, never in Terraform (PRD 16.1 rule 4).
  secret_placeholders = toset(keys(local.secret_accessors))
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

  vpc_network    = google_compute_network.vpc.name
  vpc_subnetwork = google_compute_subnetwork.run_egress.name

  # CI deploys revisions of these services only (run.developer per service,
  # never project-wide). run.developer cannot set IAM, so CI can never make
  # an internal service public.
  developers = {
    deployer = "serviceAccount:${module.wif.deployer_service_account_email}"
  }

  # Cloud Tasks delivers runs to harness with an OIDC token for this SA.
  extra_invokers = {
    # Gmail push (Pub/Sub OIDC) calls channels; the watch renew/poll jobs call
    # harness (only harness reaches connectors, PRD 6.1). Each SA holds
    # run.invoker on that one service (FR-CHN-08).
    "channels::gmail-push" = {
      service = "channels"
      member  = "serviceAccount:${google_service_account.gmail_push.account_id}@${var.project_id}.iam.gserviceaccount.com"
    }
    "harness::gmail-scheduler" = {
      service = "harness"
      member  = "serviceAccount:${google_service_account.gmail_scheduler.account_id}@${var.project_id}.iam.gserviceaccount.com"
    }
    "harness::cloud-tasks" = {
      service = "harness"
      member  = "serviceAccount:${google_service_account.tasks_invoker.account_id}@${var.project_id}.iam.gserviceaccount.com"
    }
  }

  depends_on = [google_project_service.apis]
}

# OIDC identity Cloud Tasks uses to call tilo-harness for the runs queue.
# It holds no role except run.invoker on harness (module.service).
resource "google_service_account" "tasks_invoker" {
  project      = var.project_id
  account_id   = "tilo-tasks-invoker"
  display_name = "Tilo Cloud Tasks -> harness OIDC invoker"

  depends_on = [google_project_service.apis]
}

# The enqueuers (api, harness) must be able to act as the invoker SA to
# attach its OIDC token to a task.
resource "google_service_account_iam_member" "tasks_invoker_users" {
  for_each = toset(["api", "harness"])

  service_account_id = google_service_account.tasks_invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${module.service.service_accounts[each.key]}"
}

# ---------------------------------------------------------------------------
# Identity: Workload Identity Federation for CI, project IAM bindings.
# ---------------------------------------------------------------------------

module "wif" {
  source = "../../modules/wif"

  project_id                 = var.project_id
  github_repository          = var.github_repository
  github_repository_id       = var.github_repository_id
  github_repository_owner_id = var.github_repository_owner_id

  depends_on = [google_project_service.apis]
}

module "iam" {
  source = "../../modules/iam"

  project_id = var.project_id
  bindings   = local.project_bindings

  depends_on = [google_project_service.apis]
}

# The deployer may act as each runtime SA it deploys, and nothing else.
resource "google_service_account_iam_member" "deployer_act_as" {
  for_each = local.cloud_run_services

  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.service.service_accounts[each.key]}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${module.wif.deployer_service_account_email}"
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

  # CMEK: only Cloud Storage's service agent uses the archive key; services
  # read and write the archive bucket through Storage IAM, never the key.
  archive_key_principals = {
    gcs_agent = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
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

  # The archive bucket's CMEK config (below) references module.kms.archive_key_id,
  # which is a plan-time string, not a reference to the key or its IAM grant
  # -- so Terraform would otherwise be free to create this bucket before the
  # archive key and the GCS service agent's decrypt/encrypt grant on it
  # exist, and the first apply could fail. depends_on the whole module (as
  # well as the APIs) so the bucket is created only once the key and that
  # IAM member both exist.
  depends_on = [google_project_service.apis, module.kms]

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
}

# Bucket-scoped Storage IAM (PRD 6.5 least privilege, SEC-12): grants live on
# the one bucket a service needs, never on the whole project.
#   - tilo-render writes deliverables (PPTX, PDF, charts) into "artifacts"
#     (PRD 13.2 artifact versions) and may overwrite/delete its own output.
#   - tilo-harness is the archive writer (PRD 13.2 raw archive): it may only
#     create new objects in "archive", never overwrite or delete one, so the
#     per-record hash chain cannot be tampered with after the fact.
resource "google_storage_bucket_iam_member" "render_artifacts_writer" {
  bucket = module.storage.buckets["artifacts"].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${module.service.service_accounts["render"]}"
}

resource "google_storage_bucket_iam_member" "harness_archive_writer" {
  bucket = module.storage.buckets["archive"].name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${module.service.service_accounts["harness"]}"
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

  project_id = var.project_id
  region     = var.region

  depends_on = [google_project_service.apis]
}

# PRD 15.3: harness is the only writer of events, so it is the only
# publisher on tilo-events (feeds the append-only ledger, SEC-11).
resource "google_pubsub_topic_iam_member" "events_publishers" {
  for_each = toset(["harness"])

  project = var.project_id
  topic   = module.events.topic_name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${module.service.service_accounts[each.key]}"
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

# CI pushes images to the tilo repository only, not every repo in the project.
resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  project    = var.project_id
  location   = google_artifact_registry_repository.containers.location
  repository = google_artifact_registry_repository.containers.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${module.wif.deployer_service_account_email}"
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

# Per-secret access (SEC-06, SEC-08, SEC-12): no service reads every secret.
resource "google_secret_manager_secret_iam_member" "accessors" {
  for_each = local.secret_accessor_bindings

  project   = var.project_id
  secret_id = google_secret_manager_secret.placeholders[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${module.service.service_accounts[each.value.svc]}"
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
  currency_code         = var.budget_currency_code
  threshold_percentages = [0.5, 0.9, 1.0]

  # The budget needs billingbudgets.googleapis.com enabled first.
  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Monitoring: email channel and SLO alerts (PRD 6.3, NFR-23).
# ---------------------------------------------------------------------------

module "monitoring" {
  source = "../../modules/monitoring"

  project_id              = var.project_id
  alert_email             = var.alert_email
  cloud_run_service_names = [for k in keys(local.cloud_run_services) : "tilo-${k}"]
  events_subscription_id  = module.events.subscription_name

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Storage ownership (PRD 13.2, FR-INT-02; assumptions in infra/ACCESS.md).
# Bucket-scoped, create and read only: nobody but render may overwrite.
# ---------------------------------------------------------------------------

locals {
  # bucket => service => roles
  storage_grants = {
    "artifacts" = {
      api     = ["roles/storage.objectCreator", "roles/storage.objectViewer"] # uploads (FR-INT-02), downloads (PRD 6.2)
      harness = ["roles/storage.objectCreator", "roles/storage.objectViewer"] # intermediate artifacts, masked screenshots
    }
    "snapshots" = {
      harness = ["roles/storage.objectCreator", "roles/storage.objectViewer"] # world snapshots, checkpoints (PRD 13.2)
    }
    "archive" = {
      harness = ["roles/storage.objectViewer"] # per-run hash-chain check (FR-MEM-04); create is granted above
    }
  }
  storage_bindings = { for combo in flatten([
    for bucket, svcs in local.storage_grants : [
      for svc, roles in svcs : [
        for role in roles : { key = "${bucket}::${svc}::${role}", bucket = bucket, svc = svc, role = role }
      ]
    ]
  ]) : combo.key => combo }
}

resource "google_storage_bucket_iam_member" "service_access" {
  for_each = local.storage_bindings

  bucket = module.storage.buckets[each.value.bucket].name
  role   = each.value.role
  member = "serviceAccount:${module.service.service_accounts[each.value.svc]}"
}

# ---------------------------------------------------------------------------
# Model Armor (PRD 6.3): the template the safety provider screens with.
# ---------------------------------------------------------------------------

resource "google_model_armor_template" "default" {
  project     = var.project_id
  location    = var.model_armor_location
  template_id = "tilo-default"

  filter_config {
    pi_and_jailbreak_filter_settings {
      filter_enforcement = "ENABLED"
      confidence_level   = "MEDIUM_AND_ABOVE"
    }
    malicious_uri_filter_settings {
      filter_enforcement = "ENABLED"
    }
    rai_settings {
      dynamic "rai_filters" {
        for_each = ["HATE_SPEECH", "HARASSMENT", "DANGEROUS", "SEXUALLY_EXPLICIT"]
        content {
          filter_type      = rai_filters.value
          confidence_level = "MEDIUM_AND_ABOVE"
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Gmail push (FR-CHN-08): topic, OIDC push subscription to tilo-channels and
# the Scheduler jobs that renew and poll.
# ---------------------------------------------------------------------------

resource "google_service_account" "gmail_push" {
  project      = var.project_id
  account_id   = "tilo-gmail-push"
  display_name = "Tilo Gmail push (Pub/Sub OIDC identity)"

  depends_on = [google_project_service.apis]
}

resource "google_service_account" "gmail_scheduler" {
  project      = var.project_id
  account_id   = "tilo-gmail-scheduler"
  display_name = "Tilo Gmail watch renew/poll (Cloud Scheduler OIDC identity)"

  depends_on = [google_project_service.apis]
}

module "gmail_push" {
  source = "../../modules/gmail_push"

  project_id                      = var.project_id
  region                          = var.region
  push_target_uri                 = module.service.uris["channels"]
  scheduler_target_uri            = module.service.uris["harness"]
  push_service_account_name       = google_service_account.gmail_push.name
  push_service_account_email      = google_service_account.gmail_push.email
  scheduler_service_account_email = google_service_account.gmail_scheduler.email
  pubsub_service_agent_email      = module.events.pubsub_service_agent_email

  depends_on = [google_project_service.apis]
}
