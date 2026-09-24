## Minimal test wiring for P0-07 (tilo-dev environment).
## Declares only the provider/version contract the acceptance tests in
## tests/*.tftest.hcl need to run with mock providers. No resources here:
## the builder ticket composes infra/modules/* to satisfy the tests.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
  }

  # Partial backend: bucket/prefix supplied at `terraform init -backend-config=backend.hcl`.
  # No bucket name is hard-coded here (see infra/README.md).
  backend "gcs" {}
}
