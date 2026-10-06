"""P0-07a: `.github/workflows/deploy-dev.yml`, the tilo-dev deploy pipeline (PRD 6.5, SEC-02, EFF-01, 6.6).

Pinned interface: workflow_dispatch only, Workload Identity Federation (no keys), images built on the runner and
pushed to Artifact Registry repo `tilo` in asia-southeast1 (the one `infra/` grants the deployer), seven Cloud Run
services `tilo-<svc>`. Repository variables the workflow reads: GCP_PROJECT_ID, GCP_WORKLOAD_IDENTITY_PROVIDER,
GCP_DEPLOYER_SERVICE_ACCOUNT. The deployer holds only run.developer per service, serviceAccountUser per runtime SA
and AR writer on `tilo` (infra/modules/wif, envs/dev/main.tf), so the workflow must not change IAM or ingress
(no --allow-unauthenticated, no --ingress) and cannot deploy Firebase Hosting (that stays manual).

Static only: no docker, no network, no cloud credentials.
"""

from __future__ import annotations

import pathlib
import re

import yaml

SERVICES = ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"]
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
TAINTED = ("inputs.", "github.event", "head_ref", "ref_name")


def _wf(repo_root: pathlib.Path) -> dict:
    path = repo_root / ".github" / "workflows" / "deploy-dev.yml"
    assert path.is_file(), ".github/workflows/deploy-dev.yml must exist"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _leaves(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)


def _text(wf: dict) -> str:  # comment-free: every key and scalar of the parsed workflow
    return "\n".join(_leaves(wf))


def _steps(wf: dict) -> list[dict]:
    return [s for job in wf["jobs"].values() for s in job.get("steps", [])]


def _runs(wf: dict) -> str:
    return "\n".join(s.get("run", "") for s in _steps(wf))


def _first(wf: dict, pred) -> int:
    idx = next((i for i, s in enumerate(_steps(wf)) if pred(s)), None)
    assert idx is not None, "expected step missing"
    return idx


def test_P0_07a_workflow_is_dispatch_only_with_no_free_text_inputs(repo_root: pathlib.Path) -> None:
    wf = _wf(repo_root)
    on = wf.get("on", wf.get(True))
    triggers = set(on) if isinstance(on, (dict, list)) else {on}
    assert triggers == {"workflow_dispatch"}, f"on: must be exactly workflow_dispatch, got {triggers}"
    inputs = (on.get("workflow_dispatch") or {}).get("inputs") or {} if isinstance(on, dict) else {}
    for name, spec in inputs.items():
        assert spec.get("type") in ("choice", "boolean"), f"input {name}: no free-text inputs"
        assert name.lower() not in ("env", "environment", "project", "project_id", "region", "target")
    for tainted in TAINTED:
        assert tainted not in _runs(wf), f"{tainted}: untrusted expression inside run:, pass it through env:"


def test_P0_07a_workflow_permissions_are_minimal_and_jobs_are_guarded(repo_root: pathlib.Path) -> None:
    wf = _wf(repo_root)
    assert wf.get("permissions") == {"contents": "read", "id-token": "write"}
    for name, job in wf["jobs"].items():
        assert set(job.get("permissions", {"contents": "read"}).items()) <= {
            ("contents", "read"),
            ("id-token", "write"),
        }
        cond = str(job.get("if", ""))
        assert "github.repository" in cond and "spark-456/tilo" in cond, f"{name}: must not run on forks"
        assert "refs/heads/main" in cond, f"{name}: WIF only trusts refs/heads/main (infra/modules/wif)"
        assert job.get("timeout-minutes"), f"{name}: set timeout-minutes (cost cap)"


def test_P0_07a_workflow_never_overlaps_and_never_cancels_a_running_deploy(repo_root: pathlib.Path) -> None:
    wf = _wf(repo_root)
    blocks = [wf.get("concurrency")] + [j.get("concurrency") for j in wf["jobs"].values()]
    blocks = [b for b in blocks if b]
    assert blocks, "concurrency group required"
    assert all(isinstance(b, dict) and b.get("group") and b.get("cancel-in-progress") is not True for b in blocks)


def test_P0_07a_workflow_authenticates_with_wif_only_and_pins_every_action(repo_root: pathlib.Path) -> None:
    wf = _wf(repo_root)
    steps = _steps(wf)
    uses = [s["uses"] for s in steps if "uses" in s and not s["uses"].startswith("./")]
    assert uses and all(SHA_PIN.match(u) for u in uses), f"pin every action to a full commit SHA: {uses}"
    auth = [s for s in steps if s.get("uses", "").startswith("google-github-actions/auth@")]
    assert len(auth) == 1, "exactly one google-github-actions/auth step"
    with_ = auth[0].get("with", {})
    assert "${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}" in str(with_.get("workload_identity_provider"))
    assert "${{ vars.GCP_DEPLOYER_SERVICE_ACCOUNT }}" in str(with_.get("service_account"))
    text = _text(wf)
    for banned in ["credentials_json", "GCP_SA_KEY", "GOOGLE_APPLICATION_CREDENTIALS", "activate-service-account"]:
        assert banned not in text, f"{banned}: no long-lived keys"
    for step in steps:
        if "uses" in step and step["uses"].startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False
        assert "secrets." not in str(step.get("env", "")) + step.get("run", ""), "no secrets in env or scripts"


def test_P0_07a_workflow_targets_tilo_dev_only(repo_root: pathlib.Path) -> None:
    wf = _wf(repo_root)
    text = _text(wf)
    env = wf.get("env", {})
    assert env.get("TILO_ENV") == "dev", "top-level env TILO_ENV: dev (hard-coded, not an input)"
    assert env.get("REGION") == "asia-southeast1", "top-level env REGION: asia-southeast1"
    assert "vars.GCP_PROJECT_ID" in str(env.get("PROJECT_ID")), "project id comes from the GCP_PROJECT_ID variable"
    for banned in ["tilo-demo", "terraform", "firebase deploy", "gcloud builds", "allow-unauthenticated", ":latest"]:
        assert banned not in text, f"{banned!r} must not appear (tilo-dev only; infra and IAM are not CI's job)"
    assert not re.search(r"\b" + "LI" + "VE" + r"\s*=", text), "no paid-call switch"
    assert not re.search(r"https?://[\w.-]*run\.app", text), "no hard-coded service URLs"


def test_P0_07a_workflow_builds_on_the_runner_and_pushes_to_artifact_registry(repo_root: pathlib.Path) -> None:
    runs = _runs(_wf(repo_root))
    assert "docker build" in runs and "docker push" in runs, "build and push on the runner, not Cloud Build"
    assert re.search(r"(asia-southeast1|\$\{?REGION\}?|\$\{\{\s*env\.REGION\s*\}\})-docker\.pkg\.dev", runs)
    assert re.search(r"/tilo/", runs), "Artifact Registry repo `tilo` (the one the deployer may write, infra/envs/dev)"
    assert "Dockerfile" in runs and "services/" in runs, (
        "builds services/<svc>/Dockerfile with the repo root as context"
    )
    assert re.search(r"sha256|github\.sha|GITHUB_SHA", runs), "images are addressed by digest or commit sha"


def test_P0_07a_workflow_deploys_the_seven_services_within_cost_caps(repo_root: pathlib.Path) -> None:
    wf = _wf(repo_root)
    text, runs = _text(wf), _runs(wf)
    infra = (repo_root / "infra" / "envs" / "dev" / "main.tf").read_text(encoding="utf-8")
    for svc in SERVICES:
        assert svc in text, f"{svc} missing from the deploy"
        assert re.search(rf'"{svc}"\s*=\s*\{{', infra), f"{svc} is not a Cloud Run service in infra/envs/dev"
    assert re.search(r"gcloud run (deploy|services update)", runs) and "--image" in runs
    assert "--region" in runs or "CLOUDSDK_RUN_REGION" in text
    mins = re.findall(r"--min-instances[= ]+[\"']?(\w+)", runs)
    assert mins and set(mins) == {"0"}, "min-instances 0 everywhere (scale to zero, PRD 6.5/6.6)"
    maxes = re.findall(r"--max-instances[= ]+[\"']?(\w+)", runs)
    assert maxes and all(m.isdigit() and 1 <= int(m) <= 3 for m in maxes), "max-instances 1..3 (infra uses 2-3)"
    for banned in ["--no-cpu-throttling", "--ingress", "--vpc", "--set-env-vars", "--update-env-vars"]:
        assert banned not in runs, f"{banned}: Terraform owns it; CI only swaps the image"
    for sa in re.findall(r"--service-account[= ]+(\S+)", runs):
        assert "tilo-" in sa, "per-service runtime SA (tilo-<svc>@...)"


def test_P0_07a_workflow_smoke_tests_health_after_deploy_using_deploy_outputs(repo_root: pathlib.Path) -> None:
    wf = _wf(repo_root)
    runs = _runs(wf)
    auth = _first(wf, lambda s: s.get("uses", "").startswith("google-github-actions/auth@"))
    push = _first(wf, lambda s: "docker push" in s.get("run", ""))
    deploy = _first(wf, lambda s: re.search(r"gcloud run (deploy|services update)", s.get("run", "")) is not None)
    # P0-07h (issue #397): Cloud Run reserves /healthz on run.app URLs, so the smoke step probes /health.
    smoke = _first(wf, lambda s: re.search(r"/health(?!z)", s.get("run", "")) is not None)
    assert auth < push < deploy < smoke, "order: auth, push, deploy, smoke"
    smoke_run = _steps(wf)[smoke]["run"]
    assert re.search(r"curl[^\n]*(--fail|-f\b|-sf|-fs)", smoke_run), "curl --fail on /health"
    assert re.search(r"status\.url|--format|\.url\b", runs), "URLs come from gcloud output, never typed in"
