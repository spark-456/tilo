# Licences -- infra/

Tooling and Terraform providers used to build `infra/`. This file is merged
into `docs/licences.md` by the orchestrator; it does not replace it.

| Dependency | Version | Licence | Source |
| --- | --- | --- | --- |
| Terraform CLI | >= 1.6.0 (developed against 1.16.2) | Business Source License 1.1 (BUSL-1.1) | https://github.com/hashicorp/terraform |
| `hashicorp/google` provider | ~> 6.0 (6.50.0 pinned, see `.terraform.lock.hcl`) | Mozilla Public License 2.0 (MPL-2.0) | https://github.com/hashicorp/terraform-provider-google |
| `hashicorp/google-beta` provider | ~> 6.0 (6.50.0 pinned, see `.terraform.lock.hcl`) | Mozilla Public License 2.0 (MPL-2.0) | https://github.com/hashicorp/terraform-provider-google-beta |

No provider or module code is vendored into this repository; Terraform
downloads the pinned provider binaries at `init` time from the public
Terraform registry, matching the committed `.terraform.lock.hcl`.
