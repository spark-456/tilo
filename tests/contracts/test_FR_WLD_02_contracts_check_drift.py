"""FR-WLD-02 (ticket P0-02 section 4): "`just contracts-check` validates every
fixture and regenerates into a temp dir and fails on any difference; wire
contracts-check into `just check` so CI fails on drift."

Three things, cheapest first:
1. The justfile defines a `contracts-gen` recipe and a `contracts-check`
   recipe (static check -- always runnable, no environment needed).
2. `check` (the full gate) depends on `contracts-check`, so CI fails on drift
   automatically (also static).
3. Dynamic: on a throwaway copy of the repo, `just contracts-check` exits 0
   when contracts/ and the generated packages agree, and exits non-zero after
   a schema file is edited without regenerating -- "test on a temporary
   copy", per the ticket's own test-scope note.

Test 3 copies contracts/, the two generated packages, and the files needed to
run `just` (justfile, scripts/, pyproject.toml, uv.lock, package.json,
pnpm-lock.yaml, pnpm-workspace.yaml) into pytest's tmp_path, reusing the
already-synced `.venv` via UV_PROJECT_ENVIRONMENT so it does not need to
reinstall Python dependencies. It does not copy apps/ or services/, which
contracts-check has no reason to touch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest
from _lib import SCHEMA_NAMES, find_schema_path

RUNNABLE_COPY_PATHS = (
    "contracts",
    "packages/contracts-py",
    "packages/contracts-ts",
    "scripts",
    "justfile",
    "pyproject.toml",
    "uv.lock",
    "package.json",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "tsconfig.base.json",
    ".python-version",
)

_IGNORE = shutil.ignore_patterns(".venv", "node_modules", "__pycache__", "*.pyc")


def _read_justfile(repo_root) -> str:
    return (repo_root / "justfile").read_text(encoding="utf-8")


def test_FR_WLD_02_justfile_has_contracts_gen_recipe(repo_root):
    text = _read_justfile(repo_root)
    assert "\ncontracts-gen" in text or text.startswith("contracts-gen"), (
        "FR-WLD-02: justfile must define a `contracts-gen` recipe (ticket P0-02 section 4, behind "
        "a cross-platform Python or Node script)"
    )


def test_FR_WLD_02_justfile_has_contracts_check_recipe(repo_root):
    text = _read_justfile(repo_root)
    assert "\ncontracts-check" in text or text.startswith("contracts-check"), (
        "FR-WLD-02: justfile must define a `contracts-check` recipe that validates every fixture "
        "and fails on drift (ticket P0-02 section 4)"
    )


def test_FR_WLD_02_check_recipe_depends_on_contracts_check(repo_root):
    text = _read_justfile(repo_root)
    # The `check:` recipe line lists its dependencies, e.g. "check: fmt-check lint typecheck test".
    for line in text.splitlines():
        if line.strip().startswith("check:") and not line.strip().startswith("check-fast:"):
            assert "contracts-check" in line, (
                f"FR-WLD-02: `check` must depend on `contracts-check` so CI fails on drift, got: {line!r}"
            )
            return
    pytest.fail("FR-WLD-02: justfile has no `check:` recipe to wire contracts-check into")


def _copy_runnable_repo(repo_root, dest) -> None:
    for rel in RUNNABLE_COPY_PATHS:
        src = repo_root / rel
        if not src.exists():
            continue
        target = dest / rel
        if src.is_dir():
            shutil.copytree(src, target, ignore=_IGNORE)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)


def _run_contracts_check(cwd, venv_dir) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if venv_dir.is_dir():
        env["UV_PROJECT_ENVIRONMENT"] = str(venv_dir)
    return subprocess.run(
        ["just", "contracts-check"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.slow
def test_FR_WLD_02_contracts_check_passes_when_generated_output_matches(repo_root, tmp_path):
    for name in SCHEMA_NAMES:
        path = find_schema_path(repo_root, name)
        assert path.is_file(), f"FR-WLD-02: contracts/{name}.schema.json must exist before this runs"

    work_dir = tmp_path / "clean"
    _copy_runnable_repo(repo_root, work_dir)
    result = _run_contracts_check(work_dir, repo_root / ".venv")
    assert result.returncode == 0, (
        "FR-WLD-02: `just contracts-check` must exit 0 when contracts/ and the generated packages "
        f"agree.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.mark.slow
def test_FR_WLD_02_contracts_check_fails_on_schema_drift(repo_root, tmp_path):
    common_path = find_schema_path(repo_root, "common")
    assert common_path.is_file(), "FR-WLD-02: contracts/common.schema.json must exist before this runs"

    work_dir = tmp_path / "drifted"
    _copy_runnable_repo(repo_root, work_dir)

    # Mutate a schema in the copy only, without regenerating -- this is the
    # exact drift scenario FR-WLD-02 must catch.
    rel = common_path.relative_to(repo_root)
    mutated_path = work_dir / rel
    schema = json.loads(mutated_path.read_text(encoding="utf-8"))
    schema["x-version"] = "1.0.1-drift-test"
    schema.setdefault("$defs", {})["drift_marker_field_not_in_generated_output"] = {"type": "string"}
    mutated_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    result = _run_contracts_check(work_dir, repo_root / ".venv")
    assert result.returncode != 0, (
        "FR-WLD-02: `just contracts-check` must exit non-zero when a schema changes without "
        f"regeneration.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
