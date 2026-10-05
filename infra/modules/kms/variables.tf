variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "KMS key ring location."
  type        = string
}

variable "oauth_token_decrypters" {
  description = <<-EOT
    Map of statically-known key => IAM member (e.g. "serviceAccount:...")
    allowed to encrypt and decrypt the oauth-tokens key
    (cryptoKeyEncrypterDecrypter, on this key only). Must contain only
    tilo-connectors (PRD 6.5, SEC-02). Keyed statically (not by the member
    string itself) so terraform test can plan this against mock providers.
  EOT
  type        = map(string)
}

variable "archive_key_principals" {
  description = "Map of statically-known key => IAM member allowed to encrypt/decrypt the archive key (PRD 13.2 raw archive)."
  type        = map(string)
}
