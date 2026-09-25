# Minimal VPC for Cloud Run Direct VPC egress (PRD 6.1 service-to-service
# calls). harness, connectors, browser and render use internal-only ingress;
# their callers (api, harness) send egress through this subnet so the calls
# count as internal traffic. No VMs, no Cloud NAT, no connector: Direct VPC
# egress has no standing cost (PRD 6.6 lean infrastructure).

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
