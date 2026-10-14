"""Execute the runbook's actual review gate against local Terraform plan fixtures."""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("index_create", [False, True], ids=["reviewed-plan", "index-create-stops"])
def test_runbook_review_gate(repo_root: pathlib.Path, tmp_path: pathlib.Path, index_create: bool) -> None:
    pwsh = shutil.which("pwsh")
    assert pwsh, "PowerShell 7 is required to exercise the runbook gate"
    doc = (repo_root / "docs/runbooks/infra-sitting-2.md").read_text(encoding="utf-8")
    section = doc.split("## 3. Review gate:", 1)[1].split("## 4.", 1)[0]
    block = re.search(r"```powershell\n(.*?)```", section, re.DOTALL)
    assert block, "Section 3 must contain the executable review gate"
    plan = json.loads((repo_root / "tests/repo/fixtures/runbook_gate_reviewed_plan.json").read_text(encoding="utf-8"))
    resources = plan["resource_changes"]
    assert sum(r["change"]["actions"] == ["create"] for r in resources) == 21
    assert sum(r["change"]["actions"] == ["update"] for r in resources) == 2
    assert sum("previous_address" in r for r in resources) == 1
    if index_create:
        resources.append({
            "address": "google_firestore_index.followup_retention[\"cards-owner\"]",
            "type": "google_firestore_index",
            "change": {"actions": ["create"]},
        })
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    script = tmp_path / "gate.ps1"
    # Shadow Terraform so the unmodified extracted block cannot reach cloud/state.
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "function terraform {\n"
        "  if ($args -contains '-json') { Get-Content -LiteralPath './plan.json' -Raw }\n"
        "  else { 'Plan: fixture only' }\n"
        "}\n" + block.group(1),
        encoding="utf-8",
    )
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    output = result.stdout + result.stderr
    if index_create:
        assert result.returncode != 0, output
        assert "INDEX IN THE PLAN:" in output, output
        assert "STOP: the plan is not the reviewed one" in output, output
        assert "Plan matches the reviewed list" not in output, output
    else:
        assert result.returncode == 0, output
        assert "add=21 change=2 destroy_or_replace=0 moved=1 import=0" in output, output
        assert "Plan matches the reviewed list" in output, output
