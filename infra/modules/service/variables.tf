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
    # true grants allUsers roles/run.invoker: callers carry no Google
    # identity and the service authenticates them itself (PRD 6.5, SEC-08).
    public = bool
    # Keys of other services in this map whose service account may invoke
    # this one (internal service-to-service calls, PRD 6.1).
    invoked_by = list(string)
  }))
}

variable "extra_invokers" {
  description = <<-EOT
    Additional scoped run.invoker grants keyed statically, e.g.
    "harness::cloud-tasks" => { service = "harness", member = "serviceAccount:..." }.
  EOT
  type = map(object({
    service = string
    member  = string
  }))
  default = {}
}
