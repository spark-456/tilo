variable "project_id" {
  description = "GCP project id to bind roles on."
  type        = string
}

variable "bindings" {
  description = <<-EOT
    Project-level IAM role bindings collected from all other modules, keyed
    by a statically-known string (e.g. "api::roles/datastore.user"). The key
    must not depend on any resource's computed attribute -- only the role
    and member (the map's values) may -- so terraform test can plan this
    against mock providers.
  EOT
  type = map(object({
    role   = string
    member = string
    # Optional IAM condition (null: unconditional).
    condition = optional(object({
      title       = string
      description = string
      expression  = string
    }))
  }))
}
