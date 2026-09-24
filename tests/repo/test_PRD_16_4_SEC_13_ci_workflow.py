"""PRD 16.4 SEC-13 (dependency/code scanning fails builds on critical findings)
and 6.6 EFF-01 (dev/CI make no paid model calls unless LIVE=1, proven by
blocking egress to model endpoints and the run still passing).
"""
from __future__ import annotations

import pathlib

import yaml

MODEL_ENDPOINT_HOSTS = [
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    "asia-southeast1-aiplatform.googleapis.com",
]


def _load_ci_workflow(repo_root: pathlib.Path) -> dict:
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), ".github/workflows/ci.yml must exist"
    return yaml.safe_load(ci_path.read_text(encoding="utf-8"))


def test_PRD_16_4_ci_workflow_exists(repo_root: pathlib.Path) -> None:
    _load_ci_workflow(repo_root)


def test_PRD_16_4_ci_runs_on_pull_request_and_push_to_main(repo_root: pathlib.Path) -> None:
    workflow = _load_ci_workflow(repo_root)
    # YAML parses the bare key `on` as the boolean True.
    triggers = workflow.get("on", workflow.get(True, {}))
    assert "pull_request" in triggers, "ci.yml must trigger on pull_request"
    assert "push" in triggers, "ci.yml must trigger on push"
    push_branches = triggers.get("push", {}).get("branches", []) if isinstance(triggers.get("push"), dict) else []
    assert "main" in push_branches, "ci.yml push trigger must include the main branch"


def test_PRD_16_4_ci_runs_on_ubuntu_latest(repo_root: pathlib.Path) -> None:
    workflow = _load_ci_workflow(repo_root)
    jobs = workflow.get("jobs", {})
    assert jobs, "ci.yml must define at least one job"
    runs_on_ubuntu = any(job.get("runs-on") == "ubuntu-latest" for job in jobs.values())
    assert runs_on_ubuntu, "ci.yml must run on ubuntu-latest (ADR-0001: CI runs on Linux)"


def test_EFF_01_ci_blocks_model_endpoints_before_tests(repo_root: pathlib.Path) -> None:
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), ".github/workflows/ci.yml must exist"
    text = ci_path.read_text(encoding="utf-8")

    missing_hosts = [host for host in MODEL_ENDPOINT_HOSTS if host not in text]
    assert not missing_hosts, f"ci.yml must block egress to model endpoints: {missing_hosts}"
    assert "0.0.0.0" in text, "ci.yml must map model endpoint hosts to 0.0.0.0 (e.g. via /etc/hosts)"

    workflow = _load_ci_workflow(repo_root)
    jobs = workflow.get("jobs", {})
    assert jobs, "ci.yml must define at least one job"

    for job in jobs.values():
        steps = job.get("steps", [])
        step_texts = [f"{s.get('name', '')} {s.get('run', '')}" for s in steps]
        hosts_step_idx = next(
            (i for i, t in enumerate(step_texts) if any(h in t for h in MODEL_ENDPOINT_HOSTS)),
            None,
        )
        check_step_idx = next(
            (i for i, t in enumerate(step_texts) if "just check" in t or "just setup" in t),
            None,
        )
        if hosts_step_idx is not None and check_step_idx is not None:
            assert hosts_step_idx < check_step_idx, (
                "EFF-01: the model-endpoint-blocking step must run before `just setup`/`just check`"
            )
            break
    else:
        raise AssertionError("no job blocks model endpoints before running `just check`")


def test_SEC_13_ci_runs_dependency_audit_and_can_fail_on_critical(repo_root: pathlib.Path) -> None:
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), ".github/workflows/ci.yml must exist"
    text = ci_path.read_text(encoding="utf-8")

    assert "pip-audit" in text, "SEC-13: ci.yml must run a Python dependency audit (pip-audit)"
    assert "pnpm audit" in text, "SEC-13: ci.yml must run a JS dependency audit (pnpm audit)"
    assert "audit-level" in text or "critical" in text, "SEC-13: the JS audit must be scoped to fail on critical findings"


def test_PRD_16_4_ci_workflow_has_no_secrets_or_cloud_auth(repo_root: pathlib.Path) -> None:
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_path.is_file(), ".github/workflows/ci.yml must exist"
    text = ci_path.read_text(encoding="utf-8").lower()

    for forbidden in ["google-github-actions/auth", "workload_identity_provider", "gcp_sa_key"]:
        assert forbidden not in text, f"ci.yml must not perform cloud auth yet (found `{forbidden}`)"
