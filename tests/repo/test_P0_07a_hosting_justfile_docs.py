"""P0-07a: Firebase Hosting config for apps/web, the `just deploy-dev` recipe, the runbook and the licence record.

Pinned: root `firebase.json` (firebase-tools is a root devDependency and infra/ACCESS.md deploys Hosting from the
repo root), root `.dockerignore` is covered in test_P0_07a_dockerfiles.py, runbook at `docs/deploy-dev.md`.
The CI deployer has no Firebase role, so Hosting is NOT deployed by the workflow; the web build and `firebase deploy`
stay manual (documented). Static only: no network, no gh, no cloud.
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

JUSTFILE_HEADER = re.compile(r'^deploy-dev\s+env="dev"\s*:', re.M)


def test_P0_07a_firebase_hosting_serves_the_vite_build_as_a_spa(repo_root: pathlib.Path) -> None:
    path = repo_root / "firebase.json"
    assert path.is_file(), "root firebase.json must exist"
    text = path.read_text(encoding="utf-8")
    hosting = json.loads(text)["hosting"]
    hosting = hosting[0] if isinstance(hosting, list) else hosting
    vite = (repo_root / "apps" / "web" / "vite.config.ts").read_text(encoding="utf-8")
    out_dir = (re.search(r'outDir:\s*["\']([^"\']+)["\']', vite) or [None, "dist"])[1]
    assert hosting["public"] == f"apps/web/{out_dir}", "hosting.public must be apps/web's real Vite output dir"
    pkg = json.loads((repo_root / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    assert "vite build" in pkg["scripts"]["build"], "apps/web build script must run vite build"
    # P0-07e (documented test change): the catch-all `**` became `!/assets/**`; exact source pinned in the 07e tests.
    assert any(r.get("destination") == "/index.html" for r in hosting["rewrites"]), "SPA rewrite to /index.html"
    assert not re.search(r"tilo-demo|apiKey|secret|token|essential-wares", text, re.I), "no project id or secrets here"


def test_P0_07a_just_deploy_dev_refuses_anything_but_dev_and_dispatches_the_workflow(
    repo_root: pathlib.Path,
) -> None:
    text = (repo_root / "justfile").read_text(encoding="utf-8")
    assert JUSTFILE_HEADER.search(text), 'recipe header must be `deploy-dev env="dev":` (same shape as `deploy`)'
    body = re.split(r"\n(?=\S)", text[JUSTFILE_HEADER.search(text).start() :], maxsplit=1)[0]
    refusal = re.search(r"!=\s*['\"]dev['\"]", body)
    assert refusal, "the recipe must refuse env != dev before doing anything"
    assert "deploy-dev.yml" in body and "workflow" in body and "main" in body, "dispatches deploy-dev.yml on main"
    assert body.index("deploy-dev.yml") > refusal.start(), "the refusal comes before the dispatch"
    for banned in ["tilo-demo", "terraform", "LIVE"]:
        assert banned not in body, f"{banned} must not appear in deploy-dev"
    assert "only env=dev is allowed here" in text, "the existing `deploy` recipe keeps its refusal"
    check_header = re.search(r"^check:.*$", text, re.M).group(0)
    assert "deploy" not in check_header, "`just check` must never deploy"


def test_P0_07a_runbook_documents_dispatch_wif_roles_and_dev_only(repo_root: pathlib.Path) -> None:
    path = repo_root / "docs" / "deploy-dev.md"
    assert path.is_file(), "docs/deploy-dev.md must exist"
    text = path.read_text(encoding="utf-8")
    low = text.lower()
    for need in [
        "workflow_dispatch",
        "workload identity federation",
        "tilo-dev",
        "just deploy-dev",
        "tilo-deployer",
        "run.developer",
        "artifactregistry.writer",
        "serviceaccountuser",
        "GCP_PROJECT_ID",
        "GCP_WORKLOAD_IDENTITY_PROVIDER",
        "GCP_DEPLOYER_SERVICE_ACCOUNT",
        "refs/heads/main",
        "firebase",
    ]:
        assert need.lower() in low, f"docs/deploy-dev.md must mention {need}"
    assert "never" in low and "tilo-demo" in low, "the runbook says tilo-demo is never deployed from here"
    assert "credentials_json" not in low, "the runbook must not suggest key-based auth"


def test_P0_07a_licences_doc_lists_every_action_and_base_image_the_deploy_uses(repo_root: pathlib.Path) -> None:
    doc = (repo_root / "docs" / "licences.md").read_text(encoding="utf-8").lower()
    wf = yaml.safe_load((repo_root / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8"))
    actions = {s["uses"].split("@")[0] for j in wf["jobs"].values() for s in j.get("steps", []) if "uses" in s} - {
        "actions/checkout"
    }
    assert "google-github-actions/auth" in actions, "the workflow authenticates with google-github-actions/auth"
    images: set[str] = set()
    for svc in ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"]:
        text = (repo_root / "services" / svc / "Dockerfile").read_text(encoding="utf-8")
        aliases = set(re.findall(r"^\s*FROM\s+.*\bAS\s+(\S+)", text, re.I | re.M))
        for m in re.finditer(r"^\s*FROM\s+(?:--\S+\s+)?(\S+)", text, re.I | re.M):
            if m.group(1) not in aliases and m.group(1) != "scratch":
                images.add(re.split(r"[:@]", m.group(1))[0])
    missing = sorted(x for x in actions | images if x.lower() not in doc)
    assert not missing, f"docs/licences.md must record these deploy dependencies and their licences: {missing}"
