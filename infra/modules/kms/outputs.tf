output "key_ring_id" {
  value = local.key_ring_name
}

output "oauth_tokens_key_id" {
  value = local.oauth_tokens_key_name
}

output "archive_key_id" {
  value = local.archive_key_name
}

output "oauth_token_key_decrypters" {
  description = "Echoes the members actually bound as decrypters on the oauth-tokens key."
  value       = [for m in google_kms_crypto_key_iam_member.oauth_tokens_decrypters : m.member]
}
