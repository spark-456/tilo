# Reusable piece: the tilo-dev key ring and its two keys (PRD 13.2, 16.1).
#   - oauth-tokens: envelope encryption for connector OAuth tokens. Only
#     tilo-connectors may decrypt (SEC-02).
#   - archive: encrypts the raw archive of every model/tool/channel call.
#
# Resource ids below are built from project_id/region/name rather than read
# off the resources' computed `id` attributes: KMS resource names follow a
# fixed GCP convention, and building them this way keeps outputs known at
# plan time (required for `terraform test` against mock providers).

locals {
  key_ring_name         = "projects/${var.project_id}/locations/${var.region}/keyRings/tilo-${var.region}"
  oauth_tokens_key_name = "${local.key_ring_name}/cryptoKeys/oauth-tokens"
  archive_key_name      = "${local.key_ring_name}/cryptoKeys/archive"
}

resource "google_kms_key_ring" "tilo" {
  project  = var.project_id
  name     = "tilo-${var.region}"
  location = var.region
}

resource "google_kms_crypto_key" "oauth_tokens" {
  name     = "oauth-tokens"
  key_ring = local.key_ring_name
  purpose  = "ENCRYPT_DECRYPT"

  depends_on = [google_kms_key_ring.tilo]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key" "archive" {
  name     = "archive"
  key_ring = local.key_ring_name
  purpose  = "ENCRYPT_DECRYPT"

  depends_on = [google_kms_key_ring.tilo]

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "oauth_tokens_decrypters" {
  for_each = var.oauth_token_decrypters

  crypto_key_id = local.oauth_tokens_key_name
  role          = "roles/cloudkms.cryptoKeyDecrypter"
  member        = each.value

  depends_on = [google_kms_crypto_key.oauth_tokens]
}

resource "google_kms_crypto_key_iam_member" "archive_encrypter_decrypters" {
  for_each = var.archive_key_principals

  crypto_key_id = local.archive_key_name
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value

  depends_on = [google_kms_crypto_key.archive]
}
