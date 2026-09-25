variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "buckets" {
  description = "Map of bucket key (\"artifacts\", \"archive\", \"snapshots\", PRD 6.2/6.3) => config."
  type = map(object({
    location           = string
    versioning_enabled = bool
    kms_key_name       = string # "" when the bucket is not CMEK-encrypted
    lifecycle_rules = list(object({
      action_type = string # e.g. "Delete"
      age_days    = number
    }))
  }))
}
