## Minimal test wiring for P0-07. See versions.tf.
#
# Terraform runs on the user's own application-default credentials.
# billingbudgets.googleapis.com and the Firebase APIs reject user credentials
# without a quota project, so every request is billed and quota-checked
# against var.project_id (see infra/README.md: set-quota-project).

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

provider "google-beta" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}
