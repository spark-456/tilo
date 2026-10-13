# Infrastructure sitting 2 (INFRA-SITTING2, docs/runbooks/infra-sitting-2.md). Code only: the user reviews a saved plan
# and applies it. Everything here is additive: no destroy, no replacement, no change to a retention or lifecycle rule.

locals {
  # Dedicated test-only Cloud Build identity (#870 follow-up). Same email-from-account-id pattern as tilo-cloudbuild.
  cloudbuild_tests_service_account_email = "${google_service_account.cloudbuild_tests.account_id}@${var.project_id}.iam.gserviceaccount.com"

  # Uploads (#853, FR-MEM-09): tilo-api deletes artifact bytes on an erasure request (GcsBlobBackend.delete removes every
  # generation of one key, so it needs storage.objects.delete). Predefined roles that carry it also carry more:
  # objectUser adds update, objectAdmin adds ACL and hold control, legacyBucketWriter is a legacy role. This custom role
  # holds the one permission, and is bound on the artifacts bucket only (storage_grants in main.tf). Listing and reading
  # come from objectViewer, which api already holds there. NOTE: create plus delete is, in Cloud Storage, also
  # "overwrite" for that one bucket; the application writes with if_generation_match=0 (create-only), the bucket is
  # versioned, and tilo-render already holds objectAdmin there. The archive bucket never gets this role.
  artifact_delete_role = "projects/${var.project_id}/roles/tiloArtifactObjectDelete"
}

resource "google_project_iam_custom_role" "artifact_object_delete" {
  project     = var.project_id
  role_id     = "tiloArtifactObjectDelete"
  title       = "Tilo artifact object delete"
  description = "storage.objects.delete only. Bound on the artifacts bucket for tilo-api (erasure, FR-MEM-09); never on the archive bucket."
  permissions = ["storage.objects.delete"]

  depends_on = [google_project_service.apis]
}

# ---------------------------------------------------------------------------
# Firestore TTL policies (#609, BQ-PA06B-2). The three collections live under orgs/{org}/ and every document carries an
# aware `expires_at` (people_limits_store.py, plate_links.py). A TTL policy on a collection group covers every org.
# `index_config` is deliberately omitted: the provider then leaves the field's single-field indexes as they are
# (an empty `index_config {}` block would disable them).
# ---------------------------------------------------------------------------

resource "google_firestore_field" "ttl" {
  for_each = toset(["limiter_counters", "limiter_keys", "link_nonces"])

  project    = var.project_id
  database   = google_firestore_database.default.name
  collection = each.value
  field      = "expires_at"

  ttl_config {}
}

# ---------------------------------------------------------------------------
# tilo-api reads the plate-link signing key (TILO_LINK_SIGNING_KEY, plate_links.py). The secret was created by hand on
# 13 Oct (automatic replication, one version, no binding), so it is NOT one of the placeholders in main.tf (a placeholder
# of that name would try to create it and fail, or replace it). Only the accessor binding is Terraform's.
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret_iam_member" "api_link_signing_key" {
  project   = var.project_id
  secret_id = "tilo-link-signing-key"
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${module.service.service_accounts["api"]}"
}

# ---------------------------------------------------------------------------
# Test-only Cloud Build identity (#870 follow-up). Source read on the staging bucket and build logging, nothing else:
# no Artifact Registry, no run.developer, no serviceAccountUser, no Secret Manager. The test gate
# (scripts/gate_cloud.py, cloudbuild.tests.yaml) keeps using tilo-cloudbuild until the user changes its serviceAccount.
# The project-level logWriter binding is in local.project_bindings (main.tf).
# ---------------------------------------------------------------------------

resource "google_service_account" "cloudbuild_tests" {
  project      = var.project_id
  account_id   = "tilo-cloudbuild-tests"
  display_name = "Tilo Cloud Build test gate (source read and build logs only; no deploy)"

  depends_on = [google_project_service.apis]
}

resource "google_storage_bucket_iam_member" "cloudbuild_tests_staging_viewer" {
  bucket = module.storage_cloudbuild_staging.buckets["cloudbuild-staging"].name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${local.cloudbuild_tests_service_account_email}"
}
