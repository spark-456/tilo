"""P0-07f: deploy the tilo-dev services with Google Cloud Build instead of GitHub Actions minutes (PRD 6.3, 6.5, 6.6).

Pinned interface (the Actions workflow `deploy-dev.yml` stays as an alternative; its P0-07a tests are untouched):
  * `cloudbuild.yaml` at the repo root (or `infra/cloudbuild/cloudbuild.yaml`; exactly one) builds the seven images
    from `services/<svc>/Dockerfile` with the repo root as context, pushes them to Artifact Registry repo `tilo` in
    asia-southeast1, then swaps each Cloud Run service `tilo-<svc>` to that image BY DIGEST with `--min-instances 0`
    and `--max-instances 1..3` and nothing else (no ingress / IAM / env / secrets / service-account flags: Terraform
    owns those, exactly like deploy-dev.yml).
  * The project id comes from the built-in `$PROJECT_ID` substitution, never a literal. A user substitution
    `_SERVICE` (default `all`, or one of the seven short names) mirrors the workflow's `service` input.
  * `just deploy-dev-cloudbuild service="all" env="dev"` runs `gcloud builds submit` with that config, refuses any env
    but dev before anything else, and calls only `python -c` (the refusal, same as the other recipes) and `gcloud`,
    so it runs unchanged in pwsh and sh.
  * `.gcloudignore` keeps secrets, VCS data and dependency trees out of the uploaded source.
  * `docs/deploy-dev.md`: "User's one sitting" no longer needs the three gh variables or merging #356 for services
    (Hosting stays `just deploy-web`); the Cloud Build route and the IAM its service account needs are documented as
    a separate Terraform PR the user applies.

Ambiguities resolved (PRD 6.5 states no Cloud Build detail, so the deploy-dev.yml shape is mirrored):
  * `timeout` is pinned to <= 2700 s (the workflow's `timeout-minutes: 45` cost cap).
  * `options.logging: CLOUD_LOGGING_ONLY` is pinned: no logs bucket to create, and it is required by Cloud Build as
    soon as a non-default service account runs the build (the IAM the runbook documents).
  * The recipe's positional order is service then env, so `just deploy-dev-cloudbuild api` is the common call.
  * The recipe passes `--region asia-southeast1` so the build itself runs in the Tilo region (CLAUDE.md).

Static only (plus `just --dry-run` and the refusal path, which never reach gcloud): no docker, no network, no cloud
credentials.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

SERVICES = ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"]
CANDIDATES = ("cloudbuild.yaml", "infra/cloudbuild/cloudbuild.yaml")
RECIPE_HEADER = re.compile(r"^deploy-dev-cloudbuild\b([^\n:]*):", re.M)
RUNTIME_ALLOWED_BUILDERS = re.compile(r"^(gcr\.io|[\w-]+-docker\.pkg\.dev|mirror\.gcr\.io)/")


def _config_path(repo_root: pathlib.Path) -> pathlib.Path:
    found = [repo_root / c for c in CANDIDATES if (repo_root / c).is_file()]
    assert len(found) == 1, f"exactly one Cloud Build config expected at {CANDIDATES}, found {found}"
    return found[0]


def _cfg(repo_root: pathlib.Path) -> dict:
    cfg = yaml.safe_load(_config_path(repo_root).read_text(encoding="utf-8"))
    assert isinstance(cfg, dict) and isinstance(cfg.get("steps"), list) and cfg["steps"], "steps: list required"
    return cfg


def _leaves(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield str(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _leaves(v)


def _step_text(step: dict) -> str:
    return "\n".join(_leaves({k: v for k, v in step.items() if k != "name"}))


def _text(cfg: dict) -> str:  # comment-free: every key and scalar of the parsed config
    return "\n".join(_leaves(cfg))


def _steps_text(cfg: dict) -> str:
    return "\n".join(_step_text(s) for s in cfg["steps"])


def _first_step(cfg: dict, pred) -> int:
    idx = next((i for i, s in enumerate(cfg["steps"]) if pred(_step_text(s))), None)
    assert idx is not None, "expected step missing"
    return idx


def _recipe_body(repo_root: pathlib.Path) -> str:
    text = (repo_root / "justfile").read_text(encoding="utf-8")
    m = RECIPE_HEADER.search(text)
    assert m, "justfile must define the recipe `deploy-dev-cloudbuild`"
    return re.split(r"\n(?=\S)", text[m.start() :], maxsplit=1)[0]


def _section(doc: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}[^\n]*\n", doc, re.M)
    assert m, f"docs/deploy-dev.md must keep a '## {heading}' section"
    rest = doc[m.end() :]
    nxt = re.search(r"^##\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


# --- cloudbuild.yaml ---------------------------------------------------------------------------------------------


def test_P0_07f_config_builds_the_seven_images_from_repo_root_into_the_tilo_registry(repo_root: pathlib.Path) -> None:
    cfg = _cfg(repo_root)
    text = _steps_text(cfg)
    for svc in SERVICES:
        assert re.search(rf"(?<![\w-]){re.escape(svc)}(?![\w])", text), f"{svc} missing from the build"
    assert "docker" in text and "build" in text, "images are built with docker build"
    assert re.search(r"services/[^\s'\"]*?/Dockerfile", text), "builds services/<svc>/Dockerfile"
    assert re.search(r"(--file|-f)[= ]\S*services/", text), "explicit -f services/<svc>/Dockerfile"
    flat = text.replace("\n", " ")
    assert re.search(r"(?:^|\s)\.(?:\s|$)", flat), "the build context is the repository root (`.`)"
    assert "asia-southeast1" in _text(cfg), "region asia-southeast1"
    registries = re.findall(r"([\w${}_-]+)-docker\.pkg\.dev/([^\s/]+)/([^\s/:@]+)", _text(cfg))
    assert registries, "images are pushed to Artifact Registry (<region>-docker.pkg.dev/<project>/tilo/<svc>)"
    for region, project, repo in registries:
        assert region in ("asia-southeast1", "${_REGION}", "$_REGION", "${REGION}", "$REGION", "$${REGION}"), region
        assert repo == "tilo", f"Artifact Registry repo must be `tilo`, got {repo}"
        assert project in ("$PROJECT_ID", "${PROJECT_ID}"), (
            f"project id must be the $PROJECT_ID substitution: {project}"
        )
    regions = re.findall(r"\b[a-z]+-[a-z]+\d+\b", _text(cfg))
    assert set(regions) <= {"asia-southeast1"}, f"only asia-southeast1 may appear, got {set(regions)}"
    assert "push" in text, "images are pushed before they are deployed"


def test_P0_07f_config_deploys_by_digest_within_cost_caps_and_touches_nothing_else(repo_root: pathlib.Path) -> None:
    cfg = _cfg(repo_root)
    text = _steps_text(cfg)
    flat = text.replace("\n", " ")
    assert re.search(r"\brun\s+(services\s+update|deploy)\b", flat), "deploys with gcloud run services update"
    assert "--image" in text
    assert "tilo-" in text, "Cloud Run service tilo-<svc>"
    assert "--region" in text or "CLOUDSDK_RUN_REGION" in text, "region is explicit"
    for value in re.findall(r"--image[= ]+[\"']?(\S+)", text):
        value = value.strip("\"'")
        assert "@" in value or "digest" in value.lower(), f"--image must be a digest reference, got {value!r}"
        assert not re.search(r"/[\w.-]+:[\w.${}-]+$", value), f"--image must not be a mutable tag: {value!r}"
    assert re.search(r"RepoDigests|image_summary|fully_qualified_digest|@sha256|digest", text), (
        "the deployed reference comes from the pushed image's digest"
    )
    assert ":latest" not in _text(cfg), "no :latest tag anywhere"
    mins = re.findall(r"--min-instances[= ]+[\"']?(\w+)", text)
    assert mins and set(mins) == {"0"}, "--min-instances 0 everywhere (scale to zero, PRD 6.5/6.6)"
    maxes = re.findall(r"--max-instances[= ]+[\"']?([^\s\"']+)", text)
    assert maxes, "--max-instances is required"
    literal = [m for m in maxes if not m.startswith("$")]
    assert all(m.isdigit() and 1 <= int(m) <= 3 for m in literal), "--max-instances 1..3 (infra uses 2-3)"
    if len(literal) < len(maxes):  # a shell variable: every `max=N` assignment must itself be within the cap
        assigned = re.findall(r"(?<![\w-])max\w*=[\"']?(\d+)", text, re.I)
        assert assigned and all(1 <= int(n) <= 3 for n in assigned), (
            "variable --max-instances needs max=1..3 assignments"
        )
    for banned in [
        "--ingress",
        "--allow-unauthenticated",
        "--no-allow-unauthenticated",
        "--set-env-vars",
        "--update-env-vars",
        "--remove-env-vars",
        "--clear-env-vars",
        "--set-secrets",
        "--update-secrets",
        "--remove-secrets",
        "--clear-secrets",
        "--service-account",
        "--no-cpu-throttling",
        "--vpc",
        "--add-cloudsql",
        "add-iam-policy-binding",
        "set-iam-policy",
        "remove-iam-policy-binding",
        "--member",
    ]:
        assert banned not in text, f"{banned}: Terraform owns it; Cloud Build only swaps the image"
    deploy = _first_step(cfg, lambda t: "--image" in t)
    push = _first_step(cfg, lambda t: "push" in t)
    assert push <= deploy, "order: push before deploy"


def test_P0_07f_config_takes_project_from_the_substitution_and_has_a_service_selector(
    repo_root: pathlib.Path,
) -> None:
    cfg = _cfg(repo_root)
    raw = _config_path(repo_root).read_text(encoding="utf-8")
    assert not re.search(r"essential-wares|-510320", raw), "no literal project id"
    assert "PROJECT_ID" in _steps_text(cfg), "project id comes from the $PROJECT_ID substitution"
    for m in re.finditer(r"--project[= ]+(\S+)", _steps_text(cfg)):
        assert m.group(1).strip("\"'") in ("$PROJECT_ID", "${PROJECT_ID}", "$$PROJECT_ID"), m.group(1)
    subs = cfg.get("substitutions") or {}
    assert subs.get("_SERVICE") == "all", "substitutions._SERVICE defaults to `all`, like the workflow's input"
    for k in subs:
        assert re.fullmatch(r"_[A-Z][A-Z0-9_]*", k), f"user substitutions start with an underscore: {k}"
    steps = _steps_text(cfg)
    assert "_SERVICE" in steps, "the selector is used by the steps"
    assert re.search(r"\ball\b", steps) and re.search(r"unknown service", steps, re.I), (
        "`all` or one of the seven names; anything else is refused with `unknown service`"
    )
    assert not re.search(r"\beval\b[^\n]*_SERVICE", steps), "never eval the selector"


def test_P0_07f_config_has_no_secrets_no_demo_no_paid_switch_and_a_cost_cap(repo_root: pathlib.Path) -> None:
    cfg = _cfg(repo_root)
    text = _text(cfg)
    raw = _config_path(repo_root).read_text(encoding="utf-8")
    for banned in [
        "tilo-demo",
        "terraform",
        "firebase deploy",
        "secretEnv",
        "availableSecrets",
        "secretManager",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "activate-service-account",
        "credentials_json",
        "private_key",
        "BEGIN " + "PRIVATE KEY",  # assembled at runtime: the secret scan flags the literal
        "client_secret",
    ]:
        assert banned not in text, (
            f"{banned!r} must not appear (tilo-dev only; no keys; infra is not Cloud Build's job)"
        )
    assert not re.search(r"AIza[\w-]{20,}|ya29\.|GOCSPX-|AKIA[A-Z0-9]{12,}", raw), "no key-shaped literals"
    assert not re.search(r"\b" + "LI" + "VE" + r"\s*=", text), "no paid-call switch"
    assert not re.search(r"https?://[\w.-]*run\.app", text), "no hard-coded service URLs"
    timeout = str(cfg.get("timeout", ""))
    assert re.fullmatch(r"\d+s", timeout) and 60 <= int(timeout[:-1]) <= 2700, "timeout <= 2700s (45 min cost cap)"
    assert (cfg.get("options") or {}).get("logging") == "CLOUD_LOGGING_ONLY", "options.logging: CLOUD_LOGGING_ONLY"
    for step in cfg["steps"]:
        assert RUNTIME_ALLOWED_BUILDERS.match(step["name"]), (
            f"builder image from Google's registries only: {step['name']}"
        )
        assert ":latest" not in step["name"], "no :latest builder tag"


def test_P0_07f_every_builder_image_is_recorded_in_licences(repo_root: pathlib.Path) -> None:
    doc = (repo_root / "docs" / "licences.md").read_text(encoding="utf-8").lower()
    cfg = _cfg(repo_root)
    names = {re.split(r"[:@]", s["name"])[0] for s in cfg["steps"]}
    missing = sorted(n for n in names if n.lower() not in doc)
    assert not missing, f"docs/licences.md must record these Cloud Build builder images and their licences: {missing}"


# --- .gcloudignore -----------------------------------------------------------------------------------------------


def test_P0_07f_gcloudignore_keeps_secrets_vcs_and_dependency_trees_out_of_the_upload(
    repo_root: pathlib.Path,
) -> None:
    path = repo_root / ".gcloudignore"
    assert path.is_file(), "root .gcloudignore must exist (gcloud builds submit uploads the repo root)"
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    patterns = [ln for ln in lines if ln and not ln.startswith("#")]
    effective = list(patterns)
    if any(ln.startswith("#!include:.gitignore") for ln in lines):
        effective += [
            ln.strip()
            for ln in (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    flat = "\n".join(effective)
    for need in [r"\.git/?$", r"node_modules", r"\.venv", r"\.env", r"\*\.pem", r"\*\.key"]:
        assert re.search(need, flat, re.M), f".gcloudignore must exclude {need}"
    for needed_by_dockerfiles in [
        "services",
        "packages",
        "config",
        "contracts",
        "prompts",
        "templates",
        "pyproject.toml",
        "uv.lock",
        "evals/pyproject.toml",
    ]:
        for p in effective:
            if p.startswith("!"):
                continue
            norm = p.strip("/").removeprefix("**/").rstrip("*").rstrip("/")
            assert norm != needed_by_dockerfiles, (
                f"{p}: the Dockerfiles COPY {needed_by_dockerfiles}; .dockerignore does the trimming, not .gcloudignore"
            )


# --- justfile ----------------------------------------------------------------------------------------------------


def test_P0_07f_just_recipe_refuses_anything_but_dev_and_calls_only_gcloud(repo_root: pathlib.Path) -> None:
    text = (repo_root / "justfile").read_text(encoding="utf-8")
    header = RECIPE_HEADER.search(text)
    assert header, "justfile must define the recipe `deploy-dev-cloudbuild`"
    params = header.group(1)
    assert re.search(r'\bservice="all"', params) and re.search(r'\benv="dev"', params), (
        'header must be `deploy-dev-cloudbuild service="all" env="dev":`'
    )
    assert params.index("service") < params.index("env"), "service first, env second"
    body = _recipe_body(repo_root)
    lines = [ln.strip() for ln in body.splitlines()[1:] if ln.strip()]
    assert lines, "recipe body required"
    for ln in lines:
        assert ln.startswith("python -c ") or ln.startswith("gcloud "), (
            f"recipe lines call only `python -c` (the refusal) or `gcloud`, so pwsh and sh behave alike: {ln[:60]}"
        )
    refusal = re.search(r"!=\s*['\"]dev['\"]", body)
    assert refusal, "the recipe must refuse env != dev before doing anything"
    submit = body.find("gcloud builds submit")
    assert submit > refusal.start() >= 0, "the refusal comes before `gcloud builds submit`"
    assert re.search(r"cloudbuild\.yaml", body), "submits the repo's cloudbuild.yaml"
    assert re.search(r"--config[= ]\S*cloudbuild\.yaml", body)
    assert re.search(r"--substitutions[= ]\S*_SERVICE=\{\{\s*service\s*\}\}", body), "passes _SERVICE={{service}}"
    assert re.search(r"--region[= ]asia-southeast1", body), "the build runs in asia-southeast1"
    for banned in ["tilo-demo", "terraform", "LIVE", "essential-wares", "--project", "--impersonate", "bash", "pwsh"]:
        assert banned not in body, f"{banned} must not appear in deploy-dev-cloudbuild"
    assert "only env=dev is allowed here" in text, "the existing `deploy` recipe keeps its refusal"
    assert "deploy-dev.yml" in text and re.search(r'^deploy-dev\s+env="dev"\s*:', text, re.M), "workflow recipe stays"
    check_header = re.search(r"^check:.*$", text, re.M).group(0)
    assert "deploy" not in check_header, "`just check` must never deploy"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_P0_07f_just_recipe_refuses_env_prod_before_reaching_gcloud(repo_root: pathlib.Path) -> None:
    for env in ("prod", "demo", "tilo-demo", "env=prod"):
        proc = subprocess.run(
            ["just", "--justfile", str(repo_root / "justfile"), "deploy-dev-cloudbuild", "all", env],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_root,
        )
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0, f"env={env} must be refused"
        assert "only env=dev" in out, f"refusal message must say `only env=dev`, got: {out[:200]}"
        assert "builds submit" not in out.replace("deploy-dev-cloudbuild", ""), "gcloud must not be reached"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_P0_07f_just_recipe_dry_run_submits_the_config_for_one_service_and_for_all(repo_root: pathlib.Path) -> None:
    for service in ("api", "all"):
        proc = subprocess.run(
            ["just", "--justfile", str(repo_root / "justfile"), "--dry-run", "deploy-dev-cloudbuild", service, "dev"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=repo_root,
        )
        out = proc.stdout + proc.stderr
        assert proc.returncode == 0, out
        assert "gcloud builds submit" in out
        assert f"_SERVICE={service}" in out
        assert "cloudbuild.yaml" in out and "asia-southeast1" in out


# --- docs/deploy-dev.md ------------------------------------------------------------------------------------------


def test_P0_07f_runbook_one_sitting_needs_no_gh_variables_or_356_and_documents_cloud_build_iam(
    repo_root: pathlib.Path,
) -> None:
    doc = (repo_root / "docs" / "deploy-dev.md").read_text(encoding="utf-8")
    sitting = _section(doc, "User's one sitting")
    for gone in [
        "gh variable set",
        "GCP_PROJECT_ID",
        "GCP_WORKLOAD_IDENTITY_PROVIDER",
        "GCP_DEPLOYER_SERVICE_ACCOUNT",
        "#356",
    ]:
        assert gone not in sitting, (
            f"'User's one sitting' must not require {gone} any more (services deploy via Cloud Build)"
        )
    assert "just deploy-web" in sitting, "Hosting stays `just deploy-web` in the one sitting"
    assert "just deploy-dev-cloudbuild" in sitting, "the one sitting deploys services with `just deploy-dev-cloudbuild`"
    assert "gcloud" in sitting.lower(), "the one sitting says gcloud must be signed in"

    low = doc.lower()
    for need in [
        "cloud build",
        "gcloud builds submit",
        "cloudbuild.yaml",
        "just deploy-dev-cloudbuild",
        "roles/artifactregistry.writer",
        "roles/iam.serviceaccountuser",
        "runtime service account",
        "separate terraform pr",
        "alternative",
        "_service",
    ]:
        assert need in low, f"docs/deploy-dev.md must mention {need!r}"
    assert "roles/run.developer" in low or "roles/run.admin" in low, "Cloud Run role for the Cloud Build account"
    assert re.search(r"(per service|on each|each of the seven|scoped to)", low), (
        "the Cloud Run role is scoped per service"
    )
    cloud_build_part = low[low.index("cloud build") :]
    assert not re.search(r"project[- ]level\s+`?roles/run\.admin", cloud_build_part), "no project-wide run.admin"
    assert "never" in low and "tilo-demo" in low, "the runbook still says tilo-demo is never deployed from here"
    assert "credentials_json" not in low, "no key-based auth"
    for still_documented in ["workflow_dispatch", "GCP_WORKLOAD_IDENTITY_PROVIDER", "deploy-dev.yml"]:
        assert still_documented.lower() in low, f"the Actions alternative stays documented ({still_documented})"
