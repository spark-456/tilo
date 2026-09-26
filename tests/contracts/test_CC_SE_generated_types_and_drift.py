"""FR-WLD-02 (ADR-0002 decision 8) applied to ticket CC-SE's new contracts (GitHub issues #8, #10,
#11, #12, `spark-456/tilo`): generated Python and TypeScript types must exist for every new
contract root, and `just contracts-check` must fail if a schema is edited without regenerating.
`contracts/metering.schema.json`'s generated-type and drift tests live in
`test_FR_MTR_02_...py` alongside the rest of that schema's tests, to keep one file per requirement
ID; this file covers the other four new roots (evals.schema.json/EFF-07,
attention.schema.json/FR-MTR-05, pilot.schema.json/FR-MTR-09, meter.schema.json/FR-MTR-07) so the
check is not skipped for them. Each requirement's own ID is in its test names below, even though
the underlying check (`_generated_python_type`, `_generated_typescript_type`,
`_contracts_check_fails_on_drift`) is shared, to keep the naming convention (CLAUDE.md: "Test names
contain the requirement ID").

Test-writer split: none of these schemas exist yet on this branch, so every test here must fail for
that reason.
"""

from __future__ import annotations

import json
import re

import pytest
from test_FR_WLD_02_contracts_check_drift import _copy_runnable_repo, _run_contracts_check

CONTRACTS_PY_SRC = "packages/contracts-py/src"
CONTRACTS_TS_SRC = "packages/contracts-ts/src"


def _generated_python_type(repo_root, req_id, key, name):
    src = repo_root / CONTRACTS_PY_SRC
    assert src.is_dir(), f"{req_id}: {CONTRACTS_PY_SRC}/ must exist"
    pattern = re.compile(rf"\bclass\s+{name}\b")
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in src.rglob("*.py"))
    assert hit, (
        f"{req_id}: no generated Python class {name!r} found under {CONTRACTS_PY_SRC}/ (contracts/{key}.schema.json)"
    )


def _generated_typescript_type(repo_root, req_id, key, name):
    src = repo_root / CONTRACTS_TS_SRC
    assert src.is_dir(), f"{req_id}: {CONTRACTS_TS_SRC}/ must exist"
    pattern = re.compile(rf"\b(?:interface|type)\s+{name}\b")
    ts_files = list(src.rglob("*.ts")) + list(src.rglob("*.d.ts"))
    hit = any(pattern.search(p.read_text(encoding="utf-8", errors="ignore")) for p in ts_files)
    assert hit, (
        f"{req_id}: no generated TypeScript interface/type {name!r} found under "
        f"{CONTRACTS_TS_SRC}/ (contracts/{key}.schema.json)"
    )


def _contracts_check_fails_on_drift(repo_root, tmp_path, req_id, key):
    """Mirrors test_FR_AGT_01_agents_config.py's drift test for a new schema."""
    schema_path = repo_root / "contracts" / f"{key}.schema.json"
    assert schema_path.is_file(), f"{req_id}: contracts/{key}.schema.json must exist before this runs"

    work_dir = tmp_path / f"{key}-drift"
    _copy_runnable_repo(repo_root, work_dir)

    rel = schema_path.relative_to(repo_root)
    mutated_path = work_dir / rel
    schema = json.loads(mutated_path.read_text(encoding="utf-8"))
    schema.setdefault("$defs", {})["drift_marker_field_not_in_generated_output"] = {"type": "string"}
    mutated_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")

    result = _run_contracts_check(work_dir, repo_root / ".venv")
    msg = f"{req_id}: contracts-check must fail on drift.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert result.returncode != 0, msg


def test_EFF_07_generated_python_type_exists(repo_root):
    _generated_python_type(repo_root, "EFF-07", "evals", "Evals")


def test_EFF_07_generated_typescript_type_exists(repo_root):
    _generated_typescript_type(repo_root, "EFF-07", "evals", "Evals")


@pytest.mark.slow
def test_EFF_07_contracts_check_fails_on_evals_schema_drift(repo_root, tmp_path):
    _contracts_check_fails_on_drift(repo_root, tmp_path, "EFF-07", "evals")


def test_FR_MTR_05_generated_python_type_exists(repo_root):
    _generated_python_type(repo_root, "FR-MTR-05", "attention", "Attention")


def test_FR_MTR_05_generated_typescript_type_exists(repo_root):
    _generated_typescript_type(repo_root, "FR-MTR-05", "attention", "Attention")


@pytest.mark.slow
def test_FR_MTR_05_contracts_check_fails_on_attention_schema_drift(repo_root, tmp_path):
    _contracts_check_fails_on_drift(repo_root, tmp_path, "FR-MTR-05", "attention")


def test_FR_MTR_09_generated_python_type_exists(repo_root):
    _generated_python_type(repo_root, "FR-MTR-09", "pilot", "Pilot")


def test_FR_MTR_09_generated_typescript_type_exists(repo_root):
    _generated_typescript_type(repo_root, "FR-MTR-09", "pilot", "Pilot")


@pytest.mark.slow
def test_FR_MTR_09_contracts_check_fails_on_pilot_schema_drift(repo_root, tmp_path):
    _contracts_check_fails_on_drift(repo_root, tmp_path, "FR-MTR-09", "pilot")


def test_FR_MTR_07_generated_python_type_exists(repo_root):
    _generated_python_type(repo_root, "FR-MTR-07", "meter", "Meter")


def test_FR_MTR_07_generated_typescript_type_exists(repo_root):
    _generated_typescript_type(repo_root, "FR-MTR-07", "meter", "Meter")


@pytest.mark.slow
def test_FR_MTR_07_contracts_check_fails_on_meter_schema_drift(repo_root, tmp_path):
    _contracts_check_fails_on_drift(repo_root, tmp_path, "FR-MTR-07", "meter")
