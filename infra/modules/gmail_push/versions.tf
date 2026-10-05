# Providers are inherited from the calling environment.
terraform {
  required_providers {
    google = {
      source = "hashicorp/google"
    }
  }
}
