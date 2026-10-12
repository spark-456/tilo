"""User-authorized test-only Cloud Build gate: source and spend boundaries."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("gate_cloud", ROOT / "scripts/gate_cloud.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        "apps/web/.env.local",
        "infra/envs/dev/terraform.tfstate",
        "services/api/client_secret-test.json",
        "packages/a/private.key",
        "apps/web/node_modules/a/index.js",
        ".git/config",
        "../private.txt",
    ],
)
def test_CLOUD_GATE_secret_state_and_local_artifacts_never_upload(name):
    assert not gate.allowed(name)


@pytest.mark.parametrize(
    "name",
    [
        "apps/web/src/main.tsx",
        "tests/repo/test_CLOUD_GATE_budget.py",
        "contracts/transcript.schema.json",
        ".env.example",
        "uv.lock",
    ],
)
def test_CLOUD_GATE_tracked_test_inputs_are_allowed(name):
    assert gate.allowed(name)


def test_CLOUD_GATE_budget_refuses_before_any_cloud_command(tmp_path, monkeypatch):
    (tmp_path / "CLOUD-GATE-SPEND.json").write_text(json.dumps([{"inr": 399}]))
    monkeypatch.setattr(sys, "argv", ["gate-cloud", "HEAD", "--ledger-dir", str(tmp_path)])
    real_run = gate.subprocess.run

    def git_only(command, **kwargs):
        assert command[0] == "git", "no cloud command may run after the budget threshold"
        return real_run(command, **kwargs)

    monkeypatch.setattr(gate.subprocess, "run", git_only)
    with pytest.raises(RuntimeError, match="STOP/QUESTION"):
        gate.main()
    assert not (tmp_path / "CLOUD-GATE-SPEND.lock").exists()
    assert json.loads((tmp_path / "CLOUD-GATE-SPEND.json").read_text()) == [{"inr": 399}]


def test_CLOUD_GATE_only_tests_existing_identity_and_parallel_shards():
    config = yaml.safe_load((ROOT / "cloudbuild.tests.yaml").read_text())
    assert config["serviceAccount"] == (
        "projects/$PROJECT_ID/serviceAccounts/tilo-cloudbuild@$PROJECT_ID.iam.gserviceaccount.com"
    )
    assert config["timeout"] == "1800s"
    assert config["options"]["machineType"] == "E2_HIGHCPU_8"
    assert config["options"]["logging"] == "CLOUD_LOGGING_ONLY"
    steps = {step["id"]: step for step in config["steps"]}
    assert steps["node-dependencies"]["waitFor"] == ["-"]
    assert steps["python-dependencies"]["waitFor"] == ["-"]
    assert "web" not in steps["repository"]["waitFor"]
    text = (ROOT / "cloudbuild.tests.yaml").read_text()
    assert "pytest tests/repo" in text and "vitest run" in text and "tsc --noEmit" in text
    for forbidden in ["gcloud run", "firebase deploy", "terraform apply", "LIVE=1", "availableSecrets"]:
        assert forbidden not in text
