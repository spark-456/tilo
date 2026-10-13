"""WEB-TO-API: `just deploy-web-live`, the one tilo-dev API origin in the CSP, and the runbook section.

`deploy-web` stays the fixture build (tests/repo/test_P0_07c_deploy_web.py). Static and offline.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import pytest

API = "https://tilo-api-4qhkpsn5ga-as.a.run.app"
PROJECT = "essential-wares-510320-f0"


def _recipe(root: pathlib.Path, name: str) -> str:
    text = (root / "justfile").read_text(encoding="utf-8")
    header = re.search(rf"^{re.escape(name)}(?:[ \t]+[^:\n]+)?:[^\n]*$", text, re.M)
    assert header, f"justfile must define `{name}`"
    body = [header.group(0)]
    for line in text[header.end() :].splitlines()[1:]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


@pytest.fixture(scope="module")
def script(repo_root: pathlib.Path):
    spec = importlib.util.spec_from_file_location("web_build_env_live", repo_root / "scripts" / "web_build_env.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_WEB_TO_API_live_recipe_is_pinned_to_dev_and_the_fixed_api_origin(repo_root: pathlib.Path) -> None:
    body = _recipe(repo_root, "deploy-web-live")
    assert body.splitlines()[0].strip() == "deploy-web-live:", "no parameter can change the origin or project"
    code = re.sub(r"(?m)^\s*#.*$", "", body)
    assert "python scripts/web_build_env.py --tilo-dev-api pnpm --filter @tilo/web run build" in code
    assert f"pnpm exec firebase deploy --only hosting --project {PROJECT}" in code
    assert code.index("run build") < code.index("firebase deploy")
    assert "tilo-demo" not in body and "VITE_TILO_API_URL" not in code and "{{" not in code
    assert not re.search(r"\bbash\b|\bexport\b|\$\(|`|powershell|pwsh", code, re.I)


def test_WEB_TO_API_fixture_recipe_is_untouched(repo_root: pathlib.Path) -> None:
    body = _recipe(repo_root, "deploy-web")
    assert body.splitlines()[0].strip() == 'deploy-web api="":'
    assert "--tilo-dev-api" not in body
    assert (
        "python scripts/web_build_env.py {{ if api == '' { '' } else { \"--api '\" + api + \"'\" } }} "
        "pnpm --filter @tilo/web run build" in body
    )
    assert f"pnpm exec firebase deploy --only hosting --project {PROJECT}" in body
    assert body.index("run build") < body.index("firebase deploy")


def test_WEB_TO_API_script_origin_is_a_fixed_constant_and_only_the_flag_selects_it(script) -> None:
    assert script.LIVE_API_ORIGIN == API
    assert re.fullmatch(r"https://tilo-api-[0-9a-z]+-as\.a\.run\.app", script.LIVE_API_ORIGIN)
    base = {"PATH": "p", "VITE_TILO_API_URL": "https://example.test"}
    assert script.build_env(base, {})["VITE_TILO_API_URL"] == ""  # default: the fixture world, as before
    assert script.build_env(base, {}, script.LIVE_API_ORIGIN)["VITE_TILO_API_URL"] == API
    text = (pathlib.Path(script.__file__)).read_text(encoding="utf-8")
    assert 'os.environ.get("VITE_TILO_API_URL' not in text and "tilo-demo" not in text


def test_WEB_TO_API_live_build_without_the_firebase_config_builds_nothing(script, monkeypatch) -> None:
    monkeypatch.delenv(script.BAKE_FLAG, raising=False)
    ran: list[object] = []
    monkeypatch.setattr(script, "_run", lambda *a, **k: ran.append(a) or None)
    assert script.main([script.LIVE_FLAG, "pnpm", "build"]) == 2
    assert not ran


def test_WEB_TO_API_csp_connect_src_gains_exactly_the_api_origin(repo_root: pathlib.Path) -> None:
    hosting = json.loads((repo_root / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    hosting = hosting[0] if isinstance(hosting, list) else hosting
    site = next(r for r in hosting["headers"] if r["source"] == "**")["headers"]
    csp = next(h["value"] for h in site if h["key"] == "Content-Security-Policy")
    connect = next(d for d in csp.split(";") if d.strip().startswith("connect-src")).split()[1:]
    assert connect.count(API) == 1
    assert "*" not in "".join(connect)
    run_app = [s for s in connect if s.endswith(".run.app")]
    assert run_app == [API]
    keys = {h["key"] for h in site}
    assert {"X-Content-Type-Options", "Referrer-Policy", "Cache-Control"} <= keys


def test_WEB_TO_API_runbook_lists_the_users_steps_in_order(repo_root: pathlib.Path) -> None:
    text = (repo_root / "docs" / "deploy-dev.md").read_text(encoding="utf-8")
    assert "## Test the live world on tilo-dev" in text
    section = text.split("## Test the live world on tilo-dev", 1)[1].split("\n## ", 1)[0]
    section = section[section.index("\n1. ") :]  # the numbered steps, not the intro
    needles = [
        "restrict",
        "firebase login",
        "gcloud run services update",
        "TILO_API_CORS_ORIGINS",
        "just deploy-dev-cloudbuild api",
        "just deploy-web-live",
        "sign in with Google",
    ]
    at = [section.find(n) for n in needles]
    assert all(i >= 0 for i in at), dict(zip(needles, at, strict=True))
    assert at == sorted(at), "the steps are in order"
    assert "unverified" in section.lower()
    rollout = (repo_root / "docs" / "routines-rollout.md").read_text(encoding="utf-8")
    assert '"TILO_API_CORS_ORIGINS"' in rollout.split("$Allow", 1)[1].split("$Never", 1)[0]
    questions = (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8").rstrip().splitlines()
    assert any(ln.startswith("| BQ-WEBAPI-1 ") for ln in questions)  # rows go at the end; later merges add more below
