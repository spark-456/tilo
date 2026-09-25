# google-beta is needed for google_project_service_identity (Pub/Sub agent).
# Both providers are inherited from the calling environment.

terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
    }
    google-beta = {
      source = "hashicorp/google-beta"
    }
  }
}
