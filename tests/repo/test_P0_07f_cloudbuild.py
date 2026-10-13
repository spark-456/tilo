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

Review round 1 (cost + security reviews of PR #373, documented test change; the builder fixes after):
  * Project pin: the recipe passes `--project essential-wares-510320-f0` literally (like `just deploy-web`), validates
    `service` (all or one of the seven names) before gcloud and passes it quoted. Behaviour tests run the recipe for
    real with a FAKE `gcloud` first on PATH (records its argv, never touches a network), because `just --dry-run`
    prints the recipe and cannot run the python validation.
  * Build identity: top-level `serviceAccount` is exactly tilo-cloudbuild@$PROJECT_ID (never a compute / default
    account); the docs grant the five bindings to that account only and say it fails until the Terraform PR exists.
  * `.gcloudignore` is an allowlist (`/*`, then only what the Dockerfiles COPY), checked with a small gitignore matcher.
  * Mutation-proofing: `_SERVICE` only in a step `env`, a `case` allowlist whose only `*)` is the `unknown service`
    refusal, the deploy ref must match `<region>-docker.pkg.dev/$PROJECT_ID/tilo/<svc>@sha256:` (RepoDigests), every
    builder image carries an explicit tag (cloud-sdk 587.0.0; 530.0.0 does not exist) and licences.md lists the same
    tags, and working files live in a directory step 1 creates fresh, not the root of /workspace.
  * Ambiguity: the optional `$PROJECT_ID` guard step was not pinned, so the literal project id stays banned from
    cloudbuild.yaml.

Static, plus runs of `just` against a fake gcloud: no docker, no network, no cloud credentials.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys

import pytest
import yaml

SERVICES = ["api", "harness", "channels", "connectors", "browser", "render", "sandbox-web"]
CANDIDATES = ("cloudbuild.yaml", "infra/cloudbuild/cloudbuild.yaml")
RECIPE_HEADER = re.compile(r"^deploy-dev-cloudbuild\b([^\n:]*):", re.M)
RUNTIME_ALLOWED_BUILDERS = re.compile(r"^(gcr\.io|[\w-]+-docker\.pkg\.dev|mirror\.gcr\.io)/")
DEV_PROJECT = "essential-wares-510320-f0"  # the tilo-dev project, pinned in the recipe like `just deploy-web`
BUILD_SA = "projects/$PROJECT_ID/serviceAccounts/tilo-cloudbuild@$PROJECT_ID.iam.gserviceaccount.com"
CLOUD_SDK = "gcr.io/google.com/cloudsdktool/cloud-sdk"
CLOUD_SDK_TAG = "587.0.0"  # 530.0.0 does not exist in the registry (cost review, PR #373)
TAGGED = re.compile(r"^[\w./-]+(:[\w][\w.-]*|@sha256:[0-9a-f]{64})$")
UPLOAD_ROOT_FILES = {"pyproject.toml", "uv.lock", ".dockerignore"}
UPLOAD_ROOT_DIRS = {"evals", "packages", "services", "config", "contracts", "prompts", "templates", "design"}
REINCLUDES = [
    "!/pyproject.toml",
    "!/uv.lock",
    "!/.dockerignore",
    "!/evals/",
    "!/evals/pyproject.toml",
    "!/packages/",
    "!/services/",
    "!/config/",
    "!/contracts/",
    "!/prompts/",
    "!/templates/",
    "!/design/",
    "!/design/tokens.json",
]
NESTED_DENIES = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "service-account*.json",
    "*-credentials.json",
    "application_default_credentials.json",
    "client_secret*.json",
    "token*.json",
    "*.tfplan",
    "tfplan",
    "*.tfstate*",
    "node_modules/",
    ".venv/",
]
IAM_ROLES = {
    "roles/artifactregistry.writer": "repository `tilo`",
    "roles/run.developer": "each of the seven services",
    "roles/iam.serviceaccountuser": "each of the seven runtime service accounts",
    "roles/logging.logwriter": "project level",
    "roles/storage.objectviewer": "staging bucket",
}


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


def _step_script(step: dict) -> str:
    return "\n".join(_leaves(step.get("args", [])))


def _selector_step(cfg: dict) -> dict:
    steps = [s for s in cfg["steps"] if any("_SERVICE" in str(e) for e in s.get("env", []))]
    assert len(steps) == 1, "exactly one step receives `_SERVICE`, through its env"
    return steps[0]


def _deploy_step(cfg: dict) -> dict:
    steps = [s for s in cfg["steps"] if "--image" in _step_script(s)]
    assert len(steps) == 1, "exactly one step runs `gcloud run services update --image`"
    return steps[0]


def _ignore_rules(lines: list[str]) -> list[tuple[bool, bool, re.Pattern[str]]]:
    """Tiny gitignore matcher (gcloud applies gitignore semantics): (negated, dir_only, regex) per pattern."""
    rules = []
    for raw in lines:
        pat = raw.strip()
        if not pat or pat.startswith("#"):
            continue
        neg = pat.startswith("!")
        pat = pat[1:] if neg else pat
        dir_only = pat.endswith("/")
        pat = pat.rstrip("/")
        anchored = pat.startswith("/") or "/" in pat
        pat = pat.lstrip("/")
        out, i = "", 0
        while i < len(pat):
            if pat.startswith("**/", i):
                out, i = out + "(?:.*/)?", i + 3
            elif pat.startswith("/**", i):
                out, i = out + "/.*", i + 3
            elif pat.startswith("**", i):
                out, i = out + ".*", i + 2
            elif pat[i] == "*":
                out, i = out + "[^/]*", i + 1
            elif pat[i] == "?":
                out, i = out + "[^/]", i + 1
            else:
                out, i = out + re.escape(pat[i]), i + 1
        rules.append((neg, dir_only, re.compile(("^" if anchored else "^(?:.*/)?") + out + "$")))
    return rules


def _uploaded(rules, path: str) -> bool:
    """True when `gcloud builds submit` would upload this file: no ancestor directory may be ignored (gitignore
    cannot re-include below an ignored directory), then the last matching pattern wins."""
    parts = path.split("/")
    for depth in range(1, len(parts) + 1):
        rel, is_dir = "/".join(parts[:depth]), depth < len(parts)
        ignored = False
        for neg, dir_only, rx in rules:
            if (not dir_only or is_dir) and rx.match(rel):
                ignored = not neg
        if ignored:
            return False
    return True


def _fake_gcloud(tmp_path: pathlib.Path) -> tuple[dict[str, str], pathlib.Path]:
    """A `gcloud` first on PATH that records its argv and exits 0: the recipe runs for real, nothing reaches Google."""
    log = tmp_path / "gcloud-argv.txt"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if sys.platform == "win32":
        (bindir / "gcloud.cmd").write_text('@echo off\r\necho %* > "%TILO_FAKE_GCLOUD_LOG%"\r\n', encoding="utf-8")
    else:
        exe = bindir / "gcloud"
        exe.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$TILO_FAKE_GCLOUD_LOG"\n', encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, TILO_FAKE_GCLOUD_LOG=str(log), PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    return env, log


def _just(repo_root: pathlib.Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["just", "--justfile", str(repo_root / "justfile"), "deploy-dev-cloudbuild", *args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=repo_root,
        env=env,
    )


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


def test_P0_07f_deploy_only_accepts_a_pushed_digest_of_the_selected_image(repo_root: pathlib.Path) -> None:
    cfg = _cfg(repo_root)
    build = next(s for s in cfg["steps"] if "docker push" in _step_script(s))
    assert "RepoDigests" in _step_script(build), "the digest is read from the image's RepoDigests"
    assert "RepoTags" not in _text(cfg), "RepoTags is the mutable tag, not a digest"
    deploy = _deploy_step(cfg)
    script = _step_script(deploy)
    guard = re.search(
        r"asia-southeast1-docker\.pkg\.dev/(\$\{?PROJECT_ID\}?)/tilo/[^\s\"']*@sha256:",
        script,
    )
    assert guard, (
        "the deploy step must refuse any reference that does not match "
        "asia-southeast1-docker.pkg.dev/$PROJECT_ID/tilo/<svc>@sha256: (a stray file or a tag cannot be deployed)"
    )
    assert re.search(r"\bcase\b|\[\[|\bgrep\b|=~", script) and "exit 1" in script, "the match is enforced, not logged"
    assert "$BUILD_ID" not in script and "${BUILD_ID}" not in script, "the deploy never builds a tag reference"


def test_P0_07f_working_files_live_in_a_directory_step_one_creates_fresh(repo_root: pathlib.Path) -> None:
    cfg = _cfg(repo_root)
    first = _step_script(cfg["steps"][0])
    made = re.search(r"\bmkdir\s+((?:-\w+\s+)*)[\"']?(/workspace/[\w.-]+)", first)
    assert made, "step 1 creates a fresh directory under /workspace for services.txt and the digest files"
    flags, work = made.group(1), made.group(2)
    assert not (repo_root / work.removeprefix("/workspace/")).exists(), "the directory name must not be in the repo"
    assert "-p" not in flags or re.search(rf"rm\s+-rf\s+[\"']?{re.escape(work)}", first), (
        "mkdir without -p (fails if an uploaded file planted it) or rm -rf it first"
    )
    used = set(re.findall(r"/workspace/[^\s\"'`]*", _steps_text(cfg)))
    assert used, "steps pass state through /workspace"
    for path in used:
        assert path == work or path.startswith(work + "/"), (
            f"{path}: services.txt and digest-* must be written under {work}, not the root of the uploaded source"
        )


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
    for step in cfg["steps"]:  # `_SERVICE` reaches a step only as an env entry, never spliced into a script
        for key, value in step.items():
            if key != "env":
                assert "_SERVICE" not in "\n".join(_leaves(value)), f"_SERVICE must not appear in step {key!r}"
    selector = _selector_step(cfg)
    assert all(re.fullmatch(r"[A-Z_]+=\$\{?_SERVICE\}?", e) for e in selector["env"] if "_SERVICE" in e), (
        "env entry shape NAME=$_SERVICE"
    )
    script = _step_script(selector)
    branches = re.findall(r"^\s*([^\n]*?)\)([^\n]*?);;", script, re.M)
    assert branches, "the service allowlist is a `case` statement"
    refusals = [(pat.strip(), body) for pat, body in branches if pat.strip() == "*"]
    assert len(refusals) == 1, "exactly one `*)` branch"
    assert "unknown service" in refusals[0][1] and "exit 1" in refusals[0][1], "`*)` is the `unknown service` refusal"
    assert any(pat.strip() != "*" for pat, _ in branches), "an explicit allowlist branch precedes the refusal"
    assert branches[-1][0].strip() == "*", "the refusal is the last branch"
    for svc in SERVICES:
        assert svc in script, f"{svc} must be in the allowlist"


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
    assert cfg.get("serviceAccount") == BUILD_SA, (
        f"top-level serviceAccount must be exactly {BUILD_SA} (never the Compute Engine default or legacy account)"
    )
    assert not re.search(r"compute@developer|cloudbuild\.gserviceaccount", _text(cfg)), "no default build identity"
    for step in cfg["steps"]:
        assert RUNTIME_ALLOWED_BUILDERS.match(step["name"]), (
            f"builder image from Google's registries only: {step['name']}"
        )
        assert TAGGED.match(step["name"]), f"builder image needs an explicit version tag or digest: {step['name']}"
        assert not step["name"].endswith(":latest"), "no :latest builder tag"
        if step["name"].startswith(CLOUD_SDK):
            assert step["name"] == f"{CLOUD_SDK}:{CLOUD_SDK_TAG}", f"cloud-sdk tag must be {CLOUD_SDK_TAG}"


def test_P0_07f_every_builder_image_is_recorded_in_licences(repo_root: pathlib.Path) -> None:
    doc = (repo_root / "docs" / "licences.md").read_text(encoding="utf-8")
    rows = doc.lower().splitlines()
    cfg = _cfg(repo_root)
    missing = []
    for name in sorted({s["name"] for s in cfg["steps"]}):
        image = re.split(r"[:@]", name, maxsplit=1)[0]
        tag = name[len(image) + 1 :].lower()
        if not any(image.lower() in row and re.search(rf"(?<![\w.]){re.escape(tag)}(?![\w.])", row) for row in rows):
            missing.append(name)
    assert not missing, f"docs/licences.md must list each builder image on one row with its pinned tag: {missing}"
    assert "530.0.0" not in doc, "cloud-sdk 530.0.0 does not exist"


# --- .gcloudignore -----------------------------------------------------------------------------------------------


def test_P0_07f_gcloudignore_is_an_allowlist_of_exactly_what_the_dockerfiles_copy(repo_root: pathlib.Path) -> None:
    path = repo_root / ".gcloudignore"
    assert path.is_file(), "root .gcloudignore must exist (gcloud builds submit uploads the working directory)"
    lines = path.read_text(encoding="utf-8").splitlines()
    patterns = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    assert not any(ln.startswith("#!include") for ln in (x.strip() for x in lines)), (
        "no #!include: a denylist plus .gitignore uploaded every untracked file (tfplan, meet-bot captions)"
    )
    assert patterns and patterns[0] == "/*", "the first pattern is `/*`: ignore everything, then re-include"
    assert [p for p in patterns if p.startswith("!")] == REINCLUDES, (
        f"the re-included roots are exactly {REINCLUDES} (what the Dockerfiles COPY, plus .dockerignore)"
    )
    assert patterns.index("!/evals/") < patterns.index("/evals/*") < patterns.index("!/evals/pyproject.toml"), (
        "evals: `!/evals/`, then `/evals/*`, then `!/evals/pyproject.toml`"
    )
    for deny in NESTED_DENIES:
        assert deny in patterns, f"nested deny {deny!r} must stay in .gcloudignore"

    rules = _ignore_rules(lines)
    # exact set of uploadable roots, from the real tree (an untracked newcomer must not be uploaded)
    top = {e.name for e in repo_root.iterdir()} | {"newdir", "meet-bot", "brag-output", "ORCHESTRATOR_BRIDGE.md"}
    uploaded_top = {name for name in top if _uploaded(rules, name + "/x") or _uploaded(rules, name)}
    assert uploaded_top <= UPLOAD_ROOT_FILES | UPLOAD_ROOT_DIRS, (
        f"uploaded roots must be only {sorted(UPLOAD_ROOT_FILES | UPLOAD_ROOT_DIRS)}, got {sorted(uploaded_top)}"
    )
    for need in UPLOAD_ROOT_FILES:
        assert _uploaded(rules, need), f"{need} is COPY'd or needed by the build and must be uploaded"
    assert _uploaded(rules, "design/tokens.json"), "design/tokens.json is COPY'd by render-enabled images"
    assert not _uploaded(rules, "design/sub/ok.txt"), "design allows only the root tokens file"
    assert _uploaded(rules, "evals/pyproject.toml"), "evals/pyproject.toml is COPY'd by the Dockerfiles"
    for root in sorted(UPLOAD_ROOT_DIRS - {"evals", "design"}):
        assert _uploaded(rules, f"{root}/sub/ok.txt"), f"{root}/ must be uploaded"
    for gone in [
        "evals/scripts/live_e2e.py",
        "evals/cases/x.json",
        "apps/web/index.html",
        "docs/prd/tilo-prd-v2.md",
        "infra/envs/dev/tfplan",
        "design/source/x.js",
        "meet-bot/debug/caption_snapshots/a.json",
        "README.md",
        "justfile",
        "ORCHESTRATOR_BRIDGE.md",
        "RESTART_PROMPT.md",
        ".git/config",
        ".gitignore",
        ".env",
        "newdir/file.py",
    ]:
        assert not _uploaded(rules, gone), f"{gone} must not be uploaded"
    planted = [
        ".env",
        ".env.local",
        "sub/.env.production",
        "client_secret_x.json",
        "sub/client_secret_123-abc.apps.googleusercontent.com.json",
        "token.json",
        "sub/token_gmail.json",
        "tfplan",
        "sub/dev.tfplan",
        "terraform.tfstate",
        "sub/terraform.tfstate.backup",
        "key.pem",
        "sub/a.key",
        "sub/id.p12",
        "service-account-x.json",
        "sub/gmail-credentials.json",
        "application_default_credentials.json",
        "node_modules/x/index.js",
        ".venv/lib/x.py",
    ]
    for root in sorted(UPLOAD_ROOT_DIRS):
        for rel in planted:
            assert not _uploaded(rules, f"{root}/{rel}"), f"{root}/{rel}: planted secret or state file must be excluded"


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
    gcloud_lines = [ln for ln in lines if ln.startswith("gcloud ")]
    assert len(gcloud_lines) == 1, "exactly one gcloud line"
    gcloud = gcloud_lines[0]
    assert re.search(r"""--substitutions[= ]["']_SERVICE=\{\{\s*service\s*\}\}["']""", gcloud), (
        'passes the quoted value "_SERVICE={{service}}" (a space or `;` in it must stay one argument)'
    )
    assert len(re.findall(r"\{\{\s*service\s*\}\}", gcloud)) == 1, "{{service}} appears only in that quoted value"
    assert re.search(r"--region[= ]asia-southeast1", body), "the build runs in asia-southeast1"
    assert len(re.findall(r"--project\b", gcloud)) == 1 and re.search(
        rf"--project[= ]{re.escape(DEV_PROJECT)}(?!\S)", gcloud
    ), f"gcloud pins `--project {DEV_PROJECT}` literally (like `just deploy-web`), once; no parameter overrides it"
    python_lines = [ln for ln in lines if ln.startswith("python -c ")]
    validated = (
        python_lines
        and any("{{service}}" in ln.replace(" ", "") or re.search(r"\{\{\s*service\s*\}\}", ln) for ln in python_lines)
        and all(svc in "\n".join(python_lines) for svc in SERVICES)
        and re.search(r"['\"]all['\"]", "\n".join(python_lines))
    ) or "error(" in body
    assert validated, "`service` is validated (all or one of the seven names) before gcloud runs"
    assert all(lines.index(ln) < lines.index(gcloud) for ln in python_lines), "every python check precedes gcloud"
    for banned in ["tilo-demo", "terraform", "LIVE", "--impersonate", "bash", "pwsh"]:
        assert banned not in body, f"{banned} must not appear in deploy-dev-cloudbuild"
    assert "only env=dev is allowed here" in text, "the existing `deploy` recipe keeps its refusal"
    assert "deploy-dev.yml" in text and re.search(r'^deploy-dev\s+env="dev"\s*:', text, re.M), "workflow recipe stays"
    check_header = re.search(r"^check:.*$", text, re.M).group(0)
    assert "deploy" not in check_header, "`just check` must never deploy"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_P0_07f_just_recipe_refuses_env_prod_before_reaching_gcloud(
    repo_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    env, log = _fake_gcloud(tmp_path)
    for target in ("prod", "demo", "tilo-demo", "env=prod"):
        proc = _just(repo_root, env, "all", target)
        out = proc.stdout + proc.stderr
        assert proc.returncode != 0, f"env={target} must be refused"
        assert "only env=dev" in out, f"refusal message must say `only env=dev`, got: {out[:200]}"
        assert not log.exists(), f"env={target}: gcloud must not be reached"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_P0_07f_just_recipe_refuses_a_smuggled_flag_or_command_in_service_before_gcloud(
    repo_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    # `just --dry-run` only prints the recipe and cannot run the python validation, so the recipe runs for real with
    # a fake gcloud first on PATH: a payload that gets through shows up as a recorded gcloud call.
    env, log = _fake_gcloud(tmp_path)
    for payload in (
        "api --project=some-other-project",
        "api --project some-other-project",
        "api; echo X",
        "api && echo X",
        "api' ; echo X ; '",
        'api" ; echo X ; "',
        "api,_X=1",
        "API",
        "apis",
        "all ",
        " api",
        "",
        "../api",
    ):
        proc = _just(repo_root, env, payload, "dev")
        assert proc.returncode != 0, f"service={payload!r} must be refused (all or one of the seven names)"
        assert not log.exists(), f"service={payload!r}: gcloud must not be reached"


@pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
def test_P0_07f_just_recipe_pins_the_dev_project_and_passes_service_as_one_argument(
    repo_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    env, log = _fake_gcloud(tmp_path)
    env["CLOUDSDK_CORE_PROJECT"] = "some-other-project"  # a developer's gcloud config must not decide the project
    for service in ("all", *SERVICES):
        log.unlink(missing_ok=True)
        proc = _just(repo_root, env, service, "dev")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert log.exists(), f"service={service}: gcloud was not called"
        argv = log.read_text(encoding="utf-8").replace('"', "").split()
        assert argv[:2] == ["builds", "submit"], argv
        assert argv.count("--project") == 1 and argv[argv.index("--project") + 1] == DEV_PROJECT, argv
        assert f"_SERVICE={service}" in argv, argv
        assert "--config" in argv and "cloudbuild.yaml" in argv, argv
        assert "--region" in argv and argv[argv.index("--region") + 1] == "asia-southeast1", argv
        assert not [a for a in argv if "some-other-project" in a], argv


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


def _iam_section(doc: str) -> str:
    m = re.search(r"^###\s+IAM the Cloud Build[^\n]*\n", doc, re.M)
    assert m, "docs/deploy-dev.md must keep the '### IAM the Cloud Build service account needs' section"
    rest = doc[m.end() :]
    nxt = re.search(r"^#{1,3}\s", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def test_P0_07f_runbook_grants_exactly_five_bindings_to_the_dedicated_build_account_only(
    repo_root: pathlib.Path,
) -> None:
    doc = (repo_root / "docs" / "deploy-dev.md").read_text(encoding="utf-8")
    section = _iam_section(doc)
    bullets = [b for b in re.split(r"\n(?=- )", section) if b.startswith("- ")]
    granted: dict[str, str] = {}
    for bullet in bullets:
        lead = re.match(r"- `(roles/[\w.]+)`", bullet)
        assert lead, f"every bullet starts with the role it grants: {bullet[:60]}"
        roles = [lead.group(1)]
        for role in roles:
            assert role.lower() not in granted, f"{role} granted twice"
            granted[role.lower()] = " ".join(bullet.split()).lower()
    assert set(granted) == set(IAM_ROLES), (
        f"the IAM list is exactly {sorted(IAM_ROLES)} (no roles/editor, no run.admin), got {sorted(granted)}"
    )
    for role, scope in IAM_ROLES.items():
        assert scope in re.sub(r"project-level", "project level", granted[role]), f"{role}: scope must say {scope!r}"
    assert "not project-wide" in granted["roles/artifactregistry.writer"], "AR writer is on repository `tilo` only"
    assert "never project-wide" in granted["roles/run.developer"], "run.developer is per service, never project-wide"
    assert "tilo-cloudbuild" in section, "the section grants these to tilo-cloudbuild"
    for stray in ("roles/editor", "roles/owner", "roles/run.admin", "roles/cloudbuild.builds.builder"):
        assert f"`{stray}`" not in "\n".join(bullets), f"{stray} must not be granted"

    paragraphs = [" ".join(p.split()).lower() for p in re.split(r"\n\s*\n", doc)]
    identity = [p for p in paragraphs if "tilo-cloudbuild" in p and "never" in p and "compute" in p and "legacy" in p]
    assert identity, (
        "a paragraph must name tilo-cloudbuild as the only build identity and say never the Compute Engine default "
        "or the legacy Cloud Build account"
    )
    assert "serviceaccount" in doc.lower(), "the docs point at the `serviceAccount` field of cloudbuild.yaml"
    assert BUILD_SA.lower() in doc.lower() or "tilo-cloudbuild@<project id>" in doc.lower(), (
        "the account's full name is in the docs"
    )
    fails = [p for p in paragraphs if "tilo-cloudbuild" in p and re.search(r"\bfails?\b", p) and "terraform" in p]
    assert fails, "the docs say the build fails until the separate Terraform PR creates tilo-cloudbuild"
