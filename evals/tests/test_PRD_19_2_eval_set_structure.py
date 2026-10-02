"""Set-level structure, secret-scan, and fictional-domain tests for evals (PRD 19.2, BQ-67)."""

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from conftest import REPO_ROOT
from tilo_evals import EvalsConfig, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures"
_CONFIG_PATH = REPO_ROOT / "config" / "evals.yaml"
_EMAIL_OR_URL_HOST_RE = re.compile(r"(?:@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}|https?://([A-Za-z0-9.\-]+\.[A-Za-z]{2,}))")
_PHONE_RE = re.compile(r"\+1[\s\-]?555[\s\-]?(01\d{2}|\d{4})")


def _iter_eval_files() -> list[Path]:
    files = list(_CASES_DIR.rglob("*.yaml"))
    if _FIXTURES_DIR.exists():
        files.extend(p for p in _FIXTURES_DIR.rglob("*") if p.is_file())
    return sorted(files)


def test_PRD_19_2_eval_set_structure_cases_load_and_respect_group_caps_and_contiguous_ids() -> None:
    cfg = EvalsConfig.load(str(_CONFIG_PATH))
    cases = load_cases(str(_CASES_DIR))
    assert cases, "expected eval cases under evals/cases"
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids found"
    by_group: dict[str, list[str]] = {}
    for case in cases:
        by_group.setdefault(case.group, []).append(case.id)
    counts = Counter(c.group for c in cases)
    for group, actual in counts.items():
        assert group in cfg.groups, f"unknown group {group!r}"
        assert actual <= cfg.groups[group], f"group {group} has {actual} cases, exceeds cap {cfg.groups[group]}"
        expected_ids = [f"{group}-{i:02d}" for i in range(1, actual + 1)]
        assert sorted(by_group[group]) == expected_ids, f"group {group} ids must run from 01 without gaps"


def test_PRD_19_2_eval_set_structure_no_case_or_fixture_trips_secret_scan() -> None:
    files = [str(p) for p in _iter_eval_files()]
    assert files, "expected at least one eval file to scan"
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), *files],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"secret_scan failed:\n{proc.stderr}"


def test_PRD_19_2_eval_set_structure_fictional_domains_and_phone_numbers_only() -> None:
    for path in _iter_eval_files():
        text = path.read_text(encoding="utf-8")
        for match in _EMAIL_OR_URL_HOST_RE.finditer(text):
            token = match.group(1) or match.group(0).lstrip("@")
            assert token.endswith((".example", ".invalid")), (
                f"{path.name}: host {token!r} must end with .example or .invalid"
            )
        for match in _PHONE_RE.finditer(text):
            digits = match.group(1)
            num = int(digits)
            assert 100 <= num <= 199, f"{path.name}: phone suffix {digits!r} outside 0100..0199"
