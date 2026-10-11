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
    # Direct VPC egress setting ("ALL_TRAFFIC" | "PRIVATE_RANGES_ONLY") for
    # services that call internal-only services; null = no VPC egress.
    vpc_egress = optional(string)
    # true: Terraform ignores the container env of this service (runtime
    # settings are set with `gcloud run services update`, docs/routines-rollout.md).
    # tilo-api and tilo-connectors; every other service has its env fully managed.
    ignore_env = optional(bool, false)
  }))
}

variable "vpc_network" {
  description = "VPC network name used for Direct VPC egress (services with vpc_egress set)."
  type        = string
  default     = null
}

variable "vpc_subnetwork" {
  description = "Subnetwork name in var.region used for Direct VPC egress."
  type        = string
  default     = null
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

variable "developers" {
  description = <<-EOT
    Members granted roles/run.developer on every service in var.services,
    keyed statically, e.g. { deployer = "serviceAccount:..." } (PRD 6.5 CI/CD).
  EOT
  type        = map(string)
  default     = {}
}
