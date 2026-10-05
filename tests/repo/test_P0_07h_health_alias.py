"""P0-07h (issue #397, Req P0-07a): Cloud Run reserves `/healthz` on `*.run.app` URLs.

Google's front end answers its own 404 for that path and the container never sees the request, so the
`deploy-dev.yml` smoke check and the runbook check can never pass. The fix pinned here:

* every one of the seven tilo-dev services also answers `GET /health` with the same status and body as
  `/healthz` (and `/healthz` keeps working for in-container probes);
* `.github/workflows/deploy-dev.yml` smoke and `docs/deploy-dev.md` use `/health` and no longer name `/healthz`
  as the Cloud Run check.

Service tests import each ASGI app in-process (no network, no docker), so they need the full workspace:
`uv sync --locked --all-packages` then `uv run pytest tests/repo/test_P0_07h_health_alias.py`.
"""

from __future__ import annotations

import importlib
import pathlib
import re

import pytest

# service -> the `module:attr` its Dockerfile runs under uvicorn (pinned in test_P0_07a_dockerfiles.py).
APPS = {
    "api": "tilo_api",
    "harness": "tilo_harness.app",
    "channels": "tilo_channels.app",
    "connectors": "tilo_connectors.app",
    "browser": "tilo_browser.app",
    "render": "tilo_render.app",
    "sandbox-web": "tilo_sandbox_web.app",
}


def _client(svc: str):
    testclient = importlib.import_module("fastapi.testclient")
    module = importlib.import_module(APPS[svc])
    return testclient.TestClient(module.app)


@pytest.mark.parametrize("svc", sorted(APPS))
def test_P0_07_service_answers_200_on_health_same_as_healthz(svc: str) -> None:
    client = _client(svc)
    health = client.get("/health", follow_redirects=False)
    healthz = client.get("/healthz", follow_redirects=False)
    assert health.status_code == 200, f"tilo-{svc}: GET /health must answer 200 itself, not redirect or 404"
    assert health.json() == {"status": "ok"}
    assert health.headers["content-type"].startswith("application/json")
    assert health.json() == healthz.json(), "/health has the same body as /healthz"
    assert health.headers["content-type"] == healthz.headers["content-type"]


@pytest.mark.parametrize("svc", sorted(APPS))
def test_P0_07_service_keeps_healthz_for_in_container_probes(svc: str) -> None:
    resp = _client(svc).get("/healthz", follow_redirects=False)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_P0_07_health_is_the_one_path_pinned_by_service_dockerfile_and_source(repo_root: pathlib.Path) -> None:
    # Static guard that runs without the workspace: each service source has both literal routes.
    for svc in APPS:
        src = repo_root / "services" / svc / "src"
        text = "\n".join(p.read_text(encoding="utf-8") for p in src.rglob("*.py"))
        assert '"/health"' in text, f"services/{svc}: GET /health route missing"
        assert '"/healthz"' in text, f"services/{svc}: GET /healthz must stay"


def test_P0_07_workflow_smoke_curls_health_not_healthz(repo_root: pathlib.Path) -> None:
    import yaml

    wf = yaml.safe_load((repo_root / ".github" / "workflows" / "deploy-dev.yml").read_text(encoding="utf-8"))
    runs = [s.get("run", "") for job in wf["jobs"].values() for s in job.get("steps", [])]
    smoke = [r for r in runs if "curl" in r]
    assert smoke, "a smoke step with curl must exist"
    for run in smoke:
        assert re.search(r"curl[^\n]*[\"']?\$\{?url\}?/health[\"'\s]", run + "\n"), "smoke curls ${url}/health"
        assert "/healthz" not in run, "smoke step must not reference /healthz (Cloud Run reserves it on run.app)"
        assert re.search(r"curl[^\n]*--fail", run), "curl --fail is kept"


def test_P0_07_runbook_checks_health_not_healthz(repo_root: pathlib.Path) -> None:
    doc = (repo_root / "docs" / "deploy-dev.md").read_text(encoding="utf-8")
    assert re.search(r"`/health`", doc), "docs/deploy-dev.md names the `/health` check"
    for n, line in enumerate(doc.splitlines(), 1):
        if "curl" in line:
            assert "/healthz" not in line, f"docs/deploy-dev.md:{n} still presents /healthz as the check: {line!r}"
    # Where /healthz is mentioned at all it must be to say why it is not used on run.app.
    for n, line in enumerate(doc.splitlines(), 1):
        if "/healthz" in line:
            assert re.search(r"reserved|run\.app|in-container|probe", line, re.I), (
                f"docs/deploy-dev.md:{n} mentions /healthz without saying Cloud Run reserves it"
            )
