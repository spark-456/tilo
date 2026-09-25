# Reusable piece: project-level IAM bindings, kept in one module so every
# grant in tilo-dev is visible in a single place (PRD 16.1, 16.4 SEC-12
# least-privilege service accounts). Resource-scoped bindings (KMS key
# decrypters, BigQuery ledger insert-only) live next to the resource they
# protect, in modules/kms and modules/events.

resource "google_project_iam_member" "this" {
  for_each = var.bindings

  project = var.project_id
  role    = each.value.role
  member  = each.value.member
}
