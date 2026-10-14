# Minimal VPC for Cloud Run Direct VPC egress (PRD 6.1 service-to-service
# calls). harness, connectors, browser and render use internal-only ingress;
# their callers (api, harness) send egress through this subnet so the calls
# count as internal traffic. No VMs and no connector: Direct VPC egress has no
# standing cost (PRD 6.6 lean infrastructure). Cloud NAT, below, was added in
# INFRA-SITTING2 because Private Google Access does not reach everything api
# and harness call.

resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = "tilo-vpc"
  auto_create_subnetworks = false

  depends_on = [google_project_service.apis]
}

resource "google_compute_subnetwork" "run_egress" {
  project       = var.project_id
  name          = "tilo-run-egress"
  region        = var.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = "10.10.0.0/24"

  # Lets egress-through-VPC services reach Google APIs and *.run.app
  # without external IPs.
  private_ip_google_access = true
}

# INFRA-SITTING2: Cloud NAT for the egress subnet. api and harness send ALL_TRAFFIC through this subnet (so calls to
# internal-only services count as internal), and Private Google Access only covers Google's global API VIPs and
# *.run.app. Without NAT, anything else hangs until its client times out: the regional Model Armor endpoint
# (modelarmor.<region>.rep.googleapis.com; /intake answered 503 "safety screen failed" after about 10.9 s), the NVIDIA
# NIM adapter and every vendor or connector host that api or harness calls directly. Only this subnet is NATed, with
# automatically allocated IPs: no VM, no connector, no reserved address (PRD 6.6). Cost: a small per-hour charge while
# the gateway exists plus a per-GiB charge on the traffic through it (about nothing at this scale).
# The router and the NAT were created by hand on 14 Oct (about 09:00) with exactly these names. The runbook (section 2)
# adopts them into state with `terraform import` before the saved plan (an `import` block cannot run under the mock
# providers of `terraform test`). The arguments below are the live ones, so the plan shows no change for either.
resource "google_compute_router" "nat" {
  project = var.project_id
  name    = "tilo-nat-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "run_egress" {
  project = var.project_id
  name    = "tilo-run-egress-nat"
  region  = var.region
  router  = google_compute_router.nat.name

  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.run_egress.id
    source_ip_ranges_to_nat = ["PRIMARY_IP_RANGE"] # as created by hand: the subnet has no secondary ranges in use
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
