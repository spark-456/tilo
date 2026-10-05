"""P0-07g: Terraform for the dedicated Cloud Build service account used by PR #373 (P0-07f; PRD 6.3, 6.5, SEC-12).

The IAM itself is pinned by `infra/envs/dev/tests/cloudbuild.tftest.hcl` (service account `tilo-cloudbuild`; exactly
five roles over 17 scoped bindings; Terraform-managed staging bucket in asia-southeast1 with a 7 day delete rule), run
with `terraform -chdir=infra/envs/dev test`. This file pins what a plan assertion cannot see: that the Terraform
account id is the one `cloudbuild.yaml` runs as, that the docs, the recipe and the access audit point at the same
staging bucket, and that the two older tftest assertions changed on purpose were changed narrowly.

Test changes made on purpose (documented in the tftest files too):
  * access.tftest.hcl "SEC_12_deployer_still_holds_no_project_role_by_default": used to forbid ANY `tilo-cloudbuild@`
    project binding; now allows exactly `roles/logging.logWriter` and still forbids every other project-level role.
  * wif_budget.tftest.hcl "SEC_02_deployer_cannot_change_cloud_run_iam": the `developers` set per service was
    { deployer }; it is now { deployer, tilo-cloudbuild } (same module.service `developers` map).

Ambiguities resolved (PR #373 and PRD 6.5 do not say):
  * Staging bucket name is `<project id>-cloudbuild-staging` (the name modules/storage would give key
    `cloudbuild-staging`), used as `--gcs-source-staging-dir gs://<bucket>/source`; the recipe pins the dev project id
    literally, so it carries the literal bucket name. This comes from the security review follow-up on PR #373.
  * Cross-checks that read `cloudbuild.yaml` or the `deploy-dev-cloudbuild` recipe SKIP when those files are absent:
    they exist only on feat/P0-07f-cloudbuild-deploy (PR #373) until it merges into the base this branch came from.
    The Terraform half of each check still runs and fails today.

Static only: no terraform, no network, no cloud credentials.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

DEV_PROJECT = "essential-wares-510320-f0"
STAGING_BUCKET = f"{DEV_PROJECT}-cloudbuild-staging"
SERVICES = ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"]
ACCOUNT_ID = re.compile(r'account_id\s*=\s*"(tilo-cloudbuild)"')
RECIPE_HEADER = re.compile(r"^deploy-dev-cloudbuild\b[^\n:]*:[^\n]*$", re.M)
CLOUDBUILD_YAML_CANDIDATES = ("cloudbuild.yaml", "infra/cloudbuild/cloudbuild.yaml")
FIVE_ROLES = [
    "roles/artifactregistry.writer",
    "roles/run.developer",
    "roles/iam.serviceAccountUser",
    "roles/logging.logWriter",
    "roles/storage.objectViewer",
]


def _tf_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in (repo_root / "infra").rglob("*.tf") if ".terraform" not in p.parts)


def _terraform_account_ids(repo_root: pathlib.Path) -> list[str]:
    """Every `account_id = "tilo-cloudbuild"` declared in a google_service_account resource under infra/."""
    found: list[str] = []
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for block in re.finditer(r'resource\s+"google_service_account"\s+"[^"]+"\s*\{', text):
            tail = text[block.end() : block.end() + 600]
            match = ACCOUNT_ID.search(tail.split("\nresource ")[0])
            if match:
                found.append(match.group(1))
    return found


def _recipe(repo_root: pathlib.Path) -> str | None:
    text = (repo_root / "justfile").read_text(encoding="utf-8")
    header = RECIPE_HEADER.search(text)
    if not header:
        return None
    lines = text[header.start() :].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


def test_P0_07g_terraform_declares_the_tilo_cloudbuild_service_account(repo_root: pathlib.Path) -> None:
    ids = _terraform_account_ids(repo_root)
    assert ids == ["tilo-cloudbuild"], (
        'exactly one google_service_account resource under infra/ must have account_id = "tilo-cloudbuild" '
        f"(found {ids})"
    )


def test_P0_07g_cloudbuild_yaml_runs_as_the_account_terraform_creates(repo_root: pathlib.Path) -> None:
    ids = _terraform_account_ids(repo_root)
    assert ids == ["tilo-cloudbuild"], "Terraform must declare the tilo-cloudbuild service account first"
    present = [c for c in CLOUDBUILD_YAML_CANDIDATES if (repo_root / c).is_file()]
    if not present:
        pytest.skip("cloudbuild.yaml is on feat/P0-07f-cloudbuild-deploy (PR #373); not in this base yet")
    config = yaml.safe_load((repo_root / present[0]).read_text(encoding="utf-8"))
    assert config.get("serviceAccount") == (
        f"projects/$PROJECT_ID/serviceAccounts/{ids[0]}@$PROJECT_ID.iam.gserviceaccount.com"
    ), "cloudbuild.yaml serviceAccount must name the Terraform account id on the build project"


def test_P0_07g_no_demo_project_in_infra(repo_root: pathlib.Path) -> None:
    # The no-key rule is a plan assertion (service_account_key_count == 0 in cloudbuild.tftest.hcl).
    ids = _terraform_account_ids(repo_root)
    assert ids == ["tilo-cloudbuild"], "Terraform must declare the tilo-cloudbuild service account first"
    for path in _tf_files(repo_root):
        assert "tilo-demo" not in path.read_text(encoding="utf-8"), f"{path}: nothing under infra/ targets tilo-demo"


def test_P0_07g_docs_reference_the_terraform_staging_bucket(repo_root: pathlib.Path) -> None:
    docs = (repo_root / "docs" / "deploy-dev.md").read_text(encoding="utf-8")
    assert "--gcs-source-staging-dir" in docs, (
        "docs/deploy-dev.md must say the build uploads via --gcs-source-staging-dir"
    )
    assert f"gs://{STAGING_BUCKET}" in docs, f"docs must name the staging bucket gs://{STAGING_BUCKET}"
    assert (
        "roles/storage.objectViewer" in docs and STAGING_BUCKET in docs.split("roles/storage.objectViewer", 1)[1][:400]
    ), "the objectViewer bullet must point at the named staging bucket, not 'the source staging bucket'"
    assert "7 days" in docs, "docs must state the staging bucket's 7 day lifecycle delete rule"
    for role in FIVE_ROLES:
        assert role in docs, f"docs list the five roles of tilo-cloudbuild; {role} is missing"


def test_P0_07g_access_audit_lists_the_cloudbuild_identity_and_bucket(repo_root: pathlib.Path) -> None:
    access = (repo_root / "infra" / "ACCESS.md").read_text(encoding="utf-8")
    assert "tilo-cloudbuild" in access, "infra/ACCESS.md must list the tilo-cloudbuild identity under Other identities"
    assert "cloudbuild-staging" in access, "infra/ACCESS.md must list the staging bucket"
    assert "No Cloud Build identity or staging" not in access, (
        "the old statement 'No Cloud Build identity or staging bucket exists' is now false"
    )
    for role in FIVE_ROLES:
        assert role in access, f"infra/ACCESS.md must list {role} for tilo-cloudbuild"


def test_P0_07g_recipe_submits_with_the_terraform_staging_bucket(repo_root: pathlib.Path) -> None:
    assert _terraform_account_ids(repo_root) == ["tilo-cloudbuild"], (
        "Terraform must declare the staging bucket's owner account first"
    )
    recipe = _recipe(repo_root)
    if recipe is None:
        pytest.skip("`deploy-dev-cloudbuild` is on feat/P0-07f-cloudbuild-deploy (PR #373); not in this base yet")
    assert re.search(
        rf"gcloud builds submit[^\n]*--gcs-source-staging-dir\s+\"?gs://{re.escape(STAGING_BUCKET)}(/[\w./-]*)?\"?(\s|$)",
        recipe,
    ), f"the recipe must pass --gcs-source-staging-dir gs://{STAGING_BUCKET}/<dir> (not the auto-created US bucket)"
    assert "--project essential-wares-510320-f0" in recipe, "the dev project pin from the P0-07f fix pass stays"


def test_P0_07g_the_two_deliberate_tftest_changes_stay_narrow(repo_root: pathlib.Path) -> None:
    tests = repo_root / "infra" / "envs" / "dev" / "tests"
    access = (tests / "access.tftest.hcl").read_text(encoding="utf-8")
    assert '!strcontains(b.member, "tilo-cloudbuild@") || b.role == "roles/logging.logWriter"' in access, (
        "access.tftest.hcl may allow only logWriter as a project-level role for tilo-cloudbuild"
    )
    assert "length(var.deployer_project_roles) == 0" in access
    wif = (tests / "wif_budget.tftest.hcl").read_text(encoding="utf-8")
    assert "tilo-cloudbuild@${var.project_id}.iam.gserviceaccount.com" in wif, (
        "wif_budget.tftest.hcl must name tilo-cloudbuild as the only other run.developer holder"
    )
    assert "toset(s.developers) == toset([" in wif, (
        "the developers set per service is exactly { deployer, tilo-cloudbuild }"
    )
    assert (tests / "cloudbuild.tftest.hcl").is_file()
