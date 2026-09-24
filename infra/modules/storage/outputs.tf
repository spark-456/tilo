output "buckets" {
  description = "Map of bucket key => the fields the P0-07 acceptance tests read."
  value = {
    for k, b in google_storage_bucket.this : k => {
      name                        = b.name
      location                    = b.location
      uniform_bucket_level_access = b.uniform_bucket_level_access
      versioning_enabled          = var.buckets[k].versioning_enabled
      kms_key_name                = var.buckets[k].kms_key_name
      lifecycle_rule_count        = length(var.buckets[k].lifecycle_rules)
    }
  }
}
