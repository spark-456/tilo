"""PROD-WIRE-4 (slice 4, deployed edge): `just deploy-web` gains one parameter, `api=""`, the switch between the fixture
build and a build that talks to a deployed tilo-api.

Pinned interface (test-writer brief, PROD-WIRE-4):
  * `deploy-web api=""`: empty keeps today's fixture build (`VITE_TILO_API_URL` empty, whatever the caller's own
    environment holds); non-empty must fully match tilo-api's own Cloud Run service (security round 1):
    `^https://tilo-api-[a-z0-9]+-as\\.a\\.run\\.app$` or `^https://tilo-api-[0-9]+\\.asia-southeast1\\.run\\.app$`: no
    other service name, no path, no trailing slash, no query, no port, no userinfo.
  * The check is `just`'s own (`error()` and `=~` inside `{{ }}`, like `deploy-dev-cloudbuild`), so a bad value is
    refused before any shell, python or pnpm runs and never reaches one unvalidated. A good value is passed to the
    web build as `VITE_TILO_API_URL`, and to nothing else.
  * The Firebase project stays pinned to `essential-wares-510320-f0` (no parameter changes it, never tilo-demo).

How `just` is called (ambiguity, see the report): a recipe parameter is positional, so the call is
`just deploy-web https://tilo-api-abc-as.a.run.app`. (`just deploy-web api=...` would hand the whole string
`api=...` to the recipe as the value, which the regex refuses.)

Static parse of the justfile, plus `just --dry-run`, plus real runs with a FAKE `pnpm` first on PATH that records the
`VITE_TILO_API_URL` it was started with. No firebase, no network, no cloud credentials. The run parts skip when `just`
is not installed. A bad value that reaches a shell would show up as the canary file or a recorded pnpm call.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import shutil
import stat
import subprocess
import sys

import pytest

DEV_PROJECT = "essential-wares-510320-f0"
HEADER = re.compile(r"^deploy-web\b[^\n:]*:[^\n]*$", re.M)
NEEDS_JUST = pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")

# Security round 1: only tilo-api's own Cloud Run service (infra/modules/service names it `tilo-${key}`, so `tilo-api`),
# so a typo or a pasted link can never send a person's token or build to a stranger's service.
GOOD = (
    "https://tilo-api-abc123def4-as.a.run.app",
    "https://tilo-api-4k2j9x7q1a-as.a.run.app",
    "https://tilo-api-123456789012.asia-southeast1.run.app",  # the deterministic form, pinned to the region
)

BAD = (
    "http://tilo-api-abc-as.a.run.app",  # not https
    "https://tilo-api-abc-as.a.run.app/",  # trailing slash
    "https://tilo-api-abc-as.a.run.app/v1",  # a path
    "https://tilo-api-abc-as.a.run.app?x=1",  # a query
    "https://tilo-api-abc-as.a.run.app#x",  # a fragment
    "https://tilo-api-abc-as.a.run.app:8080",  # a port
    "https://a@b.a.run.app",  # userinfo
    "https://user:pw@tilo-api-abc-as.a.run.app",
    "https://tilo-api-abc-as.a.run.app;touch pwned",
    "https://tilo-api-abc-as.a.run.app$(touch pwned)",
    "https://tilo-api-abc-as.a.run.app`touch pwned`",
    "https://tilo-api-abc-as.a.run.app&&touch pwned",
    "https://tilo-api-abc-as.a.run.app|touch pwned",
    "https://tilo-api-abc-as.a.run.app'",
    'https://tilo-api-abc-as.a.run.app"',
    "https://tilo-api-abc-as.a.run.app\\",
    "https://tilo-api-abc-as.a.run.app touch pwned",  # a space
    " https://tilo-api-abc-as.a.run.app",
    "https://tilo-api-abc-as.a.run.app ",
    "https://tilo-api-abc-as.a.run.app\n",  # `$` in the regex must not stop before a trailing newline
    "https://tilo-api-abc.firebaseapp.com",  # not Cloud Run
    "https://essential-wares-510320-f0.web.app",
    "https://tilo-api-abc-as.a.run.app.evil.test",  # suffix trick
    "https://evil.test/tilo-api-abc-as.a.run.app",
    "https://sub.tilo-api-abc-as.a.run.app",  # a dot in the label
    "https://TILO-API-ABC-AS.a.run.app",  # upper case
    "https://tilo_api.a.run.app",
    "https://.a.run.app",
    "tilo-api-abc-as.a.run.app",  # no scheme
    "http://localhost:8080",
    "https://api-123456789012.us-central1.run.app",  # the deterministic form in another region
    "https://api-12ab.asia-southeast1.run.app",  # the deterministic form needs a numeric project number
    "https://tilo-api-123456789012.asia-southeast1.run.app.evil.test",
    # security round 1: not tilo-api's own service
    "https://tilo-api.a.run.app",  # a bare label
    "https://api-123456789012.asia-southeast1.run.app",  # another service name in the deterministic form
    "https://other-svc-abc-as.a.run.app",
    "https://evil-123.asia-southeast1.run.app",
    "https://tilo-apix-abc-as.a.run.app",
    "https://xtilo-api-abc-as.a.run.app",
    "https://tilo-api-abc.a.run.app",  # not the -as form
    "https://tilo-api-abc-def-as.a.run.app",  # a dash inside the hash
    "https://tilo-api--as.a.run.app",  # no hash
    "https://tilo-api-123456789012.us-central1.run.app",
    "https://tilo-api-12ab.asia-southeast1.run.app",
)


def _text(repo_root: pathlib.Path) -> str:
    return (repo_root / "justfile").read_text(encoding="utf-8")


def _recipe(repo_root: pathlib.Path) -> str:
    text = _text(repo_root)
    header = HEADER.search(text)
    assert header, "justfile must define a `deploy-web` recipe"
    lines = text[header.start() :].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


def _fake_pnpm(tmp_path: pathlib.Path) -> tuple[dict[str, str], pathlib.Path]:
    import os

    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    log = tmp_path / "pnpm.log"
    exe = bindir / "pnpm"
    exe.write_text('#!/bin/sh\nprintf "VITE=[%s] ARGS=[%s]\\n" "$VITE_TILO_API_URL" "$*" >> "$TILO_FAKE_PNPM_LOG"\n')
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    if os.name == "nt":
        logger = bindir / "record_pnpm.py"
        logger.write_text(
            "import os, sys\n"
            "from pathlib import Path\n"
            "with Path(os.environ['TILO_FAKE_PNPM_LOG']).open('a', encoding='utf-8') as log:\n"
            "    log.write('VITE=[%s] ARGS=[%s]\\n' % "
            "(os.environ.get('VITE_TILO_API_URL', ''), ' '.join(sys.argv[1:])))\n",
            encoding="utf-8",
        )
        (bindir / "pnpm.cmd").write_text(f'@"{sys.executable}" "{logger}" %*\n', encoding="utf-8")
        assert pathlib.Path(shutil.which("pnpm", path=str(bindir)) or "") == bindir / "pnpm.cmd"
    env = dict(os.environ, TILO_FAKE_PNPM_LOG=str(log), PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    return env, log


def _just(repo_root: pathlib.Path, *args: str, env: dict[str, str] | None = None, dry: bool = False):
    cmd = ["just", "--justfile", str(repo_root / "justfile")] + (["--dry-run"] if dry else []) + ["deploy-web", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=repo_root, env=env)


# --- static: the recipe as written ----------------------------------------------------------------------------


def test_PROD_WIRE_4_deploy_web_takes_one_parameter_api_that_defaults_to_empty(repo_root: pathlib.Path) -> None:
    header = HEADER.search(_text(repo_root)).group(0)
    params = header.split(":")[0].split()[1:]

    assert params in (['api=""'], ["api=''"]), (
        f"deploy-web takes exactly one parameter, api, defaulting to empty: {header}"
    )


def test_PROD_WIRE_4_deploy_web_validates_api_in_just_itself_before_any_shell(repo_root: pathlib.Path) -> None:
    body = _recipe(repo_root)
    interpolations = " ".join(ln for ln in body.splitlines() if "{{" in ln)

    assert "error(" in interpolations and "=~" in interpolations, "validation is `{{ if api =~ ... error() }}` in just"
    assert "tilo-api-" in interpolations, "the check is pinned to tilo-api's own service name"
    assert "a\\.run\\.app" in interpolations and "asia-southeast1\\.run\\.app" in interpolations, (
        "the Cloud Run URL regex (both URL forms, the deterministic one pinned to asia-southeast1) is the check"
    )
    assert not re.search(r"re\.(match|fullmatch|search)|\bgrep\b|\[\[", body), "no shell or python validation"
    first_command = next(ln for ln in body.splitlines()[1:] if ln.strip() and not ln.strip().startswith("#"))
    assert "error(" in first_command, "the check is on the first command line, before the build or the deploy"


def test_PROD_WIRE_4_deploy_web_passes_api_to_the_build_only_and_keeps_the_dev_project_pinned(
    repo_root: pathlib.Path,
) -> None:
    body = _recipe(repo_root)
    code = re.sub(r"(?m)^\s*#.*$", "", body)

    # The base's SEC-10 build wrapper (scripts/web_build_env.py) sets VITE_TILO_API_URL, and only from its checked
    # `--api` argument; a shell value never reaches the bundle (test_SEC_10_web_build_env.py).
    assert re.search(r"web_build_env\.py \{\{[^\n]*--api[^\n]*\}\}", code), (
        "the value reaches the build through web_build_env.py --api, passed only when a url is given"
    )
    build_line = next(ln for ln in code.splitlines() if "run build" in ln)
    assert re.search(r"\{\{[^\n]*\bapi\b[^\n]*\}\}", build_line), "the parameter is interpolated into the build"
    deploy_line = next(ln for ln in code.splitlines() if "firebase deploy" in ln)
    assert "{{" not in deploy_line, "the deploy line takes no parameter: nothing can change the project or the target"
    projects = re.findall(r"--project[ =](\S+)", code)
    assert projects == [DEV_PROJECT], projects
    assert "tilo-demo" not in code


# --- just --dry-run -------------------------------------------------------------------------------------------


@NEEDS_JUST
def test_PROD_WIRE_4_dry_run_with_no_value_keeps_the_empty_fixture_build(repo_root: pathlib.Path) -> None:
    proc = _just(repo_root, dry=True)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    build_line = next(ln for ln in out.splitlines() if "run build" in ln)
    assert "--api" not in build_line, "the default build passes no --api (an empty '' is lost on older PowerShell)"
    assert re.search(r"web_build_env\.py\s+pnpm", build_line), "and the wrapper still sets VITE_TILO_API_URL empty"
    assert f"--project {DEV_PROJECT}" in out and "firebase deploy --only hosting" in out


@NEEDS_JUST
@pytest.mark.parametrize("url", GOOD)
def test_PROD_WIRE_4_dry_run_accepts_a_cloud_run_url_and_builds_with_it(repo_root: pathlib.Path, url: str) -> None:
    proc = _just(repo_root, url, dry=True)

    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    build_line = next(ln for ln in out.splitlines() if "run build" in ln)
    assert f"--api '{url}'" in build_line, build_line
    deploy_line = next(ln for ln in out.splitlines() if "firebase deploy" in ln)
    assert url not in deploy_line, "the value is for the build only, never the deploy"
    assert out.count("--project") == 1 and f"--project {DEV_PROJECT}" in out


@NEEDS_JUST
def test_PROD_WIRE_4_dry_run_refuses_every_bad_value_before_printing_a_command(repo_root: pathlib.Path) -> None:
    anchor = _just(repo_root, GOOD[0], dry=True)
    assert anchor.returncode == 0, "anchor: a good value is accepted, so refusing the bad ones means something"
    accepted = []
    for bad in BAD:
        proc = _just(repo_root, bad, dry=True)
        if proc.returncode == 0 or "firebase deploy" in proc.stdout:
            accepted.append(bad)
    assert not accepted, f"just accepted values that are not a plain Cloud Run URL: {accepted!r}"


# --- real runs with a fake pnpm -------------------------------------------------------------------------------


@NEEDS_JUST
def test_PROD_WIRE_4_a_good_url_reaches_the_build_as_vite_tilo_api_url_and_the_deploy_stays_pinned(
    repo_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    for i, url in enumerate(GOOD):
        env, log = _fake_pnpm(tmp_path / f"run{i}")
        proc = _just(repo_root, url, env=env)

        assert proc.returncode == 0, proc.stdout + proc.stderr
        calls = log.read_text(encoding="utf-8").splitlines()
        assert len(calls) == 2, calls
        assert calls[0] == f"VITE=[{url}] ARGS=[--filter @tilo/web run build]", calls[0]
        assert "exec firebase deploy --only hosting" in calls[1] and f"--project {DEV_PROJECT}" in calls[1], calls[1]
        assert url not in calls[1]


@NEEDS_JUST
def test_PROD_WIRE_4_no_value_builds_with_an_empty_url_even_if_the_callers_environment_sets_one(
    repo_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    env, log = _fake_pnpm(tmp_path)
    env["VITE_TILO_API_URL"] = "https://leak-as.a.run.app"  # a developer's shell must not turn a fixture deploy live

    proc = _just(repo_root, env=env)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert log.read_text(encoding="utf-8").splitlines()[0] == "VITE=[] ARGS=[--filter @tilo/web run build]"


@NEEDS_JUST
def test_PROD_WIRE_4_a_bad_value_never_reaches_a_shell_a_build_or_a_deploy(
    repo_root: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    env, log = _fake_pnpm(tmp_path / "anchor")
    anchor = _just(repo_root, GOOD[0], env=env)
    assert anchor.returncode == 0 and log.exists(), (
        "anchor: a good value runs, so refusing the bad ones means something"
    )
    reached = []
    for i, bad in enumerate(BAD):
        run_dir = tmp_path / f"bad{i}"
        env, log = _fake_pnpm(run_dir)
        canary = run_dir / "pwned"
        payload = bad.replace("touch pwned", f"touch {canary}")
        proc = subprocess.run(
            ["just", "--justfile", str(repo_root / "justfile"), "deploy-web", payload],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=run_dir,
            env=env,
        )
        if proc.returncode == 0 or log.exists() or canary.exists():
            reached.append(bad)
    assert not reached, f"these values got past just's own check: {reached!r}"


# --- scripts/web_build_env.py --api (the build wrapper re-checks the url; a shell value never reaches the bundle) --


def _web_build_env(repo_root: pathlib.Path):
    path = repo_root / "scripts" / "web_build_env.py"
    spec = importlib.util.spec_from_file_location("web_build_env_pw4", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_PROD_WIRE_4_web_build_env_accepts_the_tilo_api_urls_the_recipe_accepts(repo_root: pathlib.Path) -> None:
    script = _web_build_env(repo_root)
    for url in GOOD:
        assert script.API_URL.fullmatch(url), url
    for bad in BAD:
        assert bad == "" or not script.API_URL.fullmatch(bad), repr(bad)


def test_PROD_WIRE_4_web_build_env_sets_the_api_url_only_from_its_argument(
    repo_root: pathlib.Path, monkeypatch
) -> None:
    script = _web_build_env(repo_root)
    seen: list[dict[str, str]] = []
    monkeypatch.setattr(
        script, "_run", lambda argv, **kw: (seen.append(kw["env"]), subprocess.CompletedProcess(argv, 0))[1]
    )
    monkeypatch.setattr(script, "sdk_env", lambda base: {})
    monkeypatch.setenv("VITE_TILO_API_URL", "https://tilo-api-leak-as.a.run.app")

    assert script.main(["--api", GOOD[0], "pnpm", "run", "build"]) == 0
    assert script.main(["--api", "", "pnpm", "run", "build"]) == 0
    assert script.main(["pnpm", "run", "build"]) == 0
    assert [env["VITE_TILO_API_URL"] for env in seen] == [GOOD[0], "", ""], "never the shell's value"


def test_PROD_WIRE_4_web_build_env_refuses_a_bad_api_url_before_any_build(repo_root: pathlib.Path, monkeypatch) -> None:
    script = _web_build_env(repo_root)
    ran: list[list[str]] = []
    monkeypatch.setattr(script, "_run", lambda argv, **kw: (ran.append(argv), subprocess.CompletedProcess(argv, 0))[1])
    monkeypatch.setattr(script, "sdk_env", lambda base: {})
    for bad in [b for b in BAD if b] + ["https://tilo-api-abc-as.a.run.app\n"]:
        assert script.main(["--api", bad, "pnpm", "run", "build"]) == 2, repr(bad)
    assert script.main(["--api"]) == 2
    assert script.main(["--api", GOOD[0], "--api", GOOD[1], "pnpm"]) == 2, "a second --api is refused"
    assert script.main([f"--api={GOOD[0]}", "pnpm"]) == 2, "the --api=<x> form is refused"
    assert script.main(["--bake", "pnpm"]) == 2, "any other leading flag is refused"
    assert ran == [], "no build and no sdkconfig call for a refused url"
