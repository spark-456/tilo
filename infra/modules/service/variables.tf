variable "project_id" {
  description = "GCP project id."
  type        = string
}

variable "region" {
  description = "Region for every Cloud Run service."
  type        = string
}

variable "services" {
  description = <<-EOT
    Map of service key (PRD 6.2 short name, e.g. "api") => config.
    One service account and one Cloud Run v2 service are created per entry.
  EOT
  type = map(object({
    image              = string
    min_instance_count = number
    max_instance_count = number
    ingress            = string # "INGRESS_TRAFFIC_ALL" | "INGRESS_TRAFFIC_INTERNAL_ONLY"
  }))
}
