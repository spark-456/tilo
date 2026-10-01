"""Lane guard for Antigravity pull requests (docs/lanes.md; PRD 20.4 parallel work, one worktree per workstream)."""

from __future__ import annotations

import importlib.util
import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("lane_guard", REPO_ROOT / "scripts" / "lane_guard.py")
assert _spec and _spec.loader
lane_guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lane_guard)


def test_PRD_20_4_lane_guard_passes_branches_outside_the_lanes() -> None:
    assert lane_guard.violations("feat/FR-INT-09-plangraph", "phase0-stack", ["contracts/plan.schema.json"]) == []


def test_PRD_20_4_lane_guard_allows_each_lanes_own_paths() -> None:
    web = ["apps/web/src/screens/start/Start.tsx", "apps/web/e2e/flow.spec.ts", "pnpm-lock.yaml", "docs/licences.md"]
    assert lane_guard.violations("ag-web/AGW-02-s01-start", "phase0-stack", web) == []
    ev = ["evals/cases/E-RED/E-RED-01.yaml", "evals/fixtures/red/a.eml", "evals/tests/test_PRD_19_2_e_red_cases.py"]
    assert lane_guard.violations("ag-eval/AGE-02-e-red", "phase0-stack", ev) == []
    render = ["services/render/src/tilo_render/pptx.py", "templates/deck/default.yaml", "uv.lock"]
    assert lane_guard.violations("ag-render/AGR-02-pptx", "phase0-stack", render) == []


def test_PRD_20_4_lane_guard_keeps_meet_bot_out_of_antigravity() -> None:
    assert lane_guard.violations("ag-meet/VA-05-replay-harness", "chore/meet-bot-baseline", ["meet-bot/bot/x.py"])
    assert lane_guard.violations("ag-render/AGR-02-pptx", "phase0-stack", ["meet-bot/bot/x.py"])
    assert lane_guard.violations("ag-render/AGR-02-pptx", "phase0-stack", ["services/render/CLAUDE.md"])


def test_PRD_20_4_lane_guard_rejects_claude_lane_paths_and_names_each() -> None:
    files = [
        "contracts/card.schema.json",
        "docs/prd/tilo-prd-v2.md",
        "config/models.yaml",
        "services/api/src/tilo_api/intake.py",
        "apps/web/src/api/http.ts",
        "apps/web/src/world/registry.generated.ts",
        "apps/web/CLAUDE.md",
        ".github/workflows/ci.yml",
    ]
    found = lane_guard.violations("ag-web/AGW-01-flow-shell", "phase0-stack", files)
    assert len(found) == len(files)
    assert all(any(path in line for line in found) for path in files)


def test_PRD_20_4_lane_guard_keeps_lanes_apart_and_checks_the_base() -> None:
    assert lane_guard.violations("ag-eval/AGE-01-e-plan", "phase0-stack", ["apps/web/src/App.tsx"])
    assert lane_guard.violations("ag-eval/AGE-01-e-plan", "phase0-stack", ["evals/src/tilo_evals/checks.py"])
    assert lane_guard.violations("ag-web/AGW-01-flow-shell", "main", ["apps/web/src/App.tsx"])


def test_PRD_20_4_ci_runs_the_lane_guard_on_ag_branches() -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["lane-guard"]
    assert "startsWith(github.head_ref, 'ag-')" in job["if"]
    assert job["steps"][0].get("with", {}).get("fetch-depth") == 0
    run = " ".join(step.get("run", "") for step in job["steps"])
    assert "scripts/lane_guard.py" in run
    # Branch names are attacker-chosen text: they reach the script through env, never inline in `run`.
    assert "${{" not in run
