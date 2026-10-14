"""W22: the hosted release smoke (`just smoke-hosted`, apps/web/e2e/hosted-smoke.spec.ts).

It must never reach the network by itself: the spec skips when TILO_SMOKE_URL is unset, the main Playwright
config ignores it, and the recipe accepts only a Firebase Hosting origin. The slip it exists for (a build with no
Firebase config showing "Sign-in is off") must be asserted by name, and the release doc must describe it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = REPO_ROOT / "apps/web/e2e/hosted-smoke.spec.ts"
HOSTED_CONFIG = REPO_ROOT / "apps/web/playwright.hosted.config.ts"
MAIN_CONFIG = REPO_ROOT / "apps/web/playwright.config.ts"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_W22_spec_skips_itself_without_a_url():
    spec = _read(SPEC)
    assert "TILO_SMOKE_URL" in spec
    assert re.search(r"test\.skip\(\s*!URL_UNDER_TEST", spec)


def test_W22_spec_asserts_the_13_oct_regression_and_the_demo_path():
    spec = _read(SPEC)
    for needle in (
        "Continue with Google",
        "Explore a demo session",
        "sign-in is off",
        "park-page-home",
        "park-page-worlds",
        "park-page-world",
        "/settings",
        "Fixture replay",
        "r.status() >= 400",
    ):
        assert needle in spec, needle


def test_W22_main_playwright_config_ignores_the_hosted_spec_and_hosted_config_has_no_server():
    assert "hosted-smoke.spec.ts" in _read(MAIN_CONFIG)
    assert "HOSTED_SPECS" in re.search(r"testIgnore: \[[^\]]*\]", _read(MAIN_CONFIG)).group(0)
    hosted = _read(HOSTED_CONFIG)
    assert "webServer" not in re.sub(r"//.*", "", hosted)
    assert "hosted-smoke.spec.ts" in hosted


def test_W22_recipe_accepts_only_a_hosting_origin_and_is_documented():
    just = _read(REPO_ROOT / "justfile")
    m = re.search(r"^smoke-hosted url=\"\":\n(.*?)\n\n", just, re.M | re.S)
    assert m, "smoke-hosted recipe"
    body = m.group(1)
    assert "error(" in body.splitlines()[0], "the url check is on the first line"
    assert "web\.app" in body and "firebaseapp" in body
    assert "playwright.hosted.config.ts" in body
    assert "## Hosted smoke" in _read(REPO_ROOT / "docs/deploy-dev.md")


def test_W22_WIN_recipe_passes_url_and_failure_without_network(tmp_path):
    """Run the real recipe with a fake pnpm; never start a browser or contact Hosting."""
    capture = tmp_path / "capture.json"
    stub = tmp_path / "stub.cjs"
    stub.write_text(
        "require('node:fs').writeFileSync(process.env.W22_CAPTURE, JSON.stringify({"
        "url:process.env.TILO_SMOKE_URL,cwd:process.cwd(),args:process.argv.slice(2)}));"
        "process.exit(7);",
        encoding="utf-8",
    )
    launcher = tmp_path / ("pnpm.cmd" if os.name == "nt" else "pnpm")
    launcher.write_text(
        f'@node "{stub}" %*\n' if os.name == "nt" else f'#!/bin/sh\nnode "{stub}" "$@"\n',
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", "W22_CAPTURE": str(capture)}
    result = subprocess.run(
        ["just", "--justfile", str(REPO_ROOT / "justfile"), "smoke-hosted", "https://w22-test.web.app"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert capture.exists(), result.stdout + result.stderr
    recorded = json.loads(capture.read_text(encoding="utf-8"))
    assert recorded["url"] == "https://w22-test.web.app"
    assert Path(recorded["cwd"]) == REPO_ROOT / "apps/web"
    assert recorded["args"] == ["exec", "playwright", "test", "--config", "playwright.hosted.config.ts"]
    assert result.returncode != 0, "a failed smoke must fail the recipe"
