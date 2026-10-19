"""PROD-WIRE slice 3, security round 1 (ADR-0026): tilo-api runs exactly one instance, and no deploy path may undo it.

Kill switches and revocation live in one process's cache, so a second api instance would not see them. Terraform's
`max_instance_count = 1` is the revision maximum, and so is `gcloud run services update --max-instances`: a pipeline
that sets 3 on every deploy overrides Terraform after the first deploy. This file pins the api value in all three
places together (`infra/envs/dev/main.tf`, `.github/workflows/deploy-dev.yml`, `cloudbuild.yaml`) and the docs.
The other services' values are not pinned here (their own tests do).
"""

from __future__ import annotations

import pathlib
import re

from test_PROD_WIRE_3_api_service_terraform import _services  # same directory: pytest rootdir-relative import


def _deploy_max(text: str, service: str) -> list[str]:
    """The `--max-instances` values of every `update <service> ...` line of a deploy script."""
    return re.findall(rf"^\s*update\s+{re.escape(service)}\s+.*?--max-instances[= ]+(\S+)", text, re.M)


def test_PROD_WIRE_3_terraform_api_max_instance_count_is_one(repo_root: pathlib.Path) -> None:
    api = _services(repo_root)["api"]
    assert re.findall(r"^\s*max_instance_count\s*=\s*(\d+)", api, re.M) == ["1"]


def test_PROD_WIRE_3_the_github_workflow_deploys_api_with_one_max_instance(repo_root: pathlib.Path) -> None:
    text = (repo_root / ".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")
    assert _deploy_max(text, "api") == ["1"], "the workflow must not raise the api revision maximum above Terraform's 1"


def test_PROD_WIRE_3_cloudbuild_deploys_api_with_one_max_instance(repo_root: pathlib.Path) -> None:
    text = (repo_root / "cloudbuild.yaml").read_text(encoding="utf-8")
    assert _deploy_max(text, "api") == ["1"], "Cloud Build must not raise the api revision maximum above Terraform's 1"


def test_PROD_WIRE_3_the_other_services_keep_their_maximums(repo_root: pathlib.Path) -> None:
    expected = {"harness": "3", "channels": "3", "connectors": "1", "browser": "2", "render": "2", "sandbox-web": "2"}
    for path in (".github/workflows/deploy-dev.yml", "cloudbuild.yaml"):
        text = (repo_root / path).read_text(encoding="utf-8")
        for service, value in expected.items():
            assert _deploy_max(text, service) == [value], f"{path}: {service}"


def test_PROD_WIRE_3_the_deploy_doc_says_api_is_one_instance(repo_root: pathlib.Path) -> None:
    text = (repo_root / "docs/deploy-dev.md").read_text(encoding="utf-8")
    assert "--max-instances 2..3" not in text, "the doc must not say every service is 2..3"
    assert re.search(r"tilo-api[^\n]*(one|1) instance|api[^\n]*--max-instances 1", text, re.I), (
        "the doc names the api's single instance (ADR-0026)"
    )
