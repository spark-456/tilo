"""Set-level structure, secret-scan, and fictional-domain tests for evals (PRD 19.2, BQ-67)."""

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from _evals_lib import REPO_ROOT
from tilo_evals import EvalsConfig, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures"
_CONFIG_PATH = REPO_ROOT / "config" / "evals.yaml"
_EMAIL_OR_URL_HOST_RE = re.compile(r"(?:@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}|https?://([A-Za-z0-9.\-]+\.[A-Za-z]{2,}))")
_PHONE_RE = re.compile(r"\+1[\s\-]?555[\s\-]?(01\d{2}|\d{4})")
DENYLIST_BRANDS_RE = re.compile(
    r"\b(?:Google(?:\s+Drive)?|BeautifulSoup|Microsoft|Slack|Dropbox|Amazon|Apple|OpenAI"
    r"|Yanmar|Johnson\s+pump|Pettit|Interlux|Wells\s+Fargo|GreenDot|Seattle\s+Boat\s+Show"
    r"|Pacific\s+Northwest\s+Marine\s+Trades|seattlecharters"
    r"|Vermeer|Northwind|Contoso|AdventureWorks)\b",
    re.IGNORECASE,
)
REAL_ROUTING_RE = re.compile(
    r"\b(?!0{3}[- ]?0{3}[- ]?0{3}\b)\d{3}[- ]?\d{3}[- ]?\d{3}\b"
    r"|\b(?!0{4}[- ]0{4}[- ]0\b)\d{4}[- ]\d{4}[- ]\d\b"
    r"|\b(?!0{10,12}\b)\d{10,12}\b"
)


def _iter_eval_files() -> list[Path]:
    files = list(_CASES_DIR.rglob("*.yaml"))
    if _FIXTURES_DIR.exists():
        files.extend(p for p in _FIXTURES_DIR.rglob("*") if p.is_file())
    return sorted(files)


# Cases ADR-0029 adds on top of the PRD 19.2 rows (BQ-LW16-1); the rows and `config/evals.yaml` (EFF-07) stay at 160.
_ADR_EXTRAS = {"E-RES-11"}


def test_PRD_19_2_eval_set_structure_cases_load_and_respect_group_caps_and_contiguous_ids() -> None:
    cfg = EvalsConfig.load(str(_CONFIG_PATH))
    every = load_cases(str(_CASES_DIR))
    assert {c.id for c in every} >= _ADR_EXTRAS, "an ADR-0029 extra case is missing"
    cases = [c for c in every if c.id not in _ADR_EXTRAS]
    assert len(cases) == sum(cfg.groups.values()) == 160, f"expected all 160 eval cases, got {len(cases)}"
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids)), "duplicate case ids found"
    by_group: dict[str, list[str]] = {}
    for case in cases:
        by_group.setdefault(case.group, []).append(case.id)
    counts = Counter(c.group for c in cases)
    assert dict(counts) == cfg.groups, f"expected all 8 groups complete {cfg.groups}, got {dict(counts)}"
    for group, expected_count in cfg.groups.items():
        expected_ids = [f"{group}-{i:02d}" for i in range(1, expected_count + 1)]
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
        brand_match = DENYLIST_BRANDS_RE.search(f"{path.name}\n{text}")
        assert brand_match is None, f"{path.name}: real brand {brand_match.group(0)!r} found"
        routing_match = REAL_ROUTING_RE.search(text)
        assert routing_match is None, f"{path.name}: routing/account number {routing_match.group(0)!r} found"
        for match in _EMAIL_OR_URL_HOST_RE.finditer(text):
            token = match.group(1) or match.group(0).lstrip("@")
            assert token.endswith((".example", ".invalid")), (
                f"{path.name}: host {token!r} must end with .example or .invalid"
            )
        for match in _PHONE_RE.finditer(text):
            digits = match.group(1)
            num = int(digits)
            assert 100 <= num <= 199, f"{path.name}: phone suffix {digits!r} outside 0100..0199"


DESCRIPTIVE_GROUND_TRUTH_KEYS: set[tuple[str, str]] = {
    ("E-CHN", "must_not"),
    ("E-CHN", "must_show"),
    ("E-CHN", "topic_keywords"),
    ("E-MAIL", "reason"),
    ("E-RED", "bait"),
}

_DEDICATED_CHECK_FIELDS: dict[str, set[str]] = {
    "recipients_within": {"allowed_recipients"},
    "no_invented_commitments": {"forbidden_commitments"},
    "routed_domain": {"domain"},
    "answered_from_decision": {"answered_from_decision", "decision_id"},
    "flagged_or_blocked": {"expected"},
    "no_side_effects": {"side_effects"},
}


def test_PRD_19_2_eval_set_structure_every_ground_truth_key_is_graded_or_marked_descriptive() -> None:
    cases = load_cases(str(_CASES_DIR))
    assert len(cases) == 160 + len(_ADR_EXTRAS)
    for case in cases:
        gt = case.ground_truth or {}
        graded: set[str] = set()
        for entry in case.checks:
            chk = entry["check"]
            args = entry.get("args", {})
            if chk == "equals_ground_truth" and "field" in args:
                graded.add(args["field"])
            elif chk in _DEDICATED_CHECK_FIELDS:
                graded |= _DEDICATED_CHECK_FIELDS[chk]
        for key in gt:
            if key in graded:
                continue
            assert (case.group, key) in DESCRIPTIVE_GROUND_TRUTH_KEYS, (
                f"{case.id}: ground_truth.{key} is neither graded by a check nor listed as descriptive"
            )
            assert case.notes and "descriptive" in case.notes.lower() and key in case.notes, (
                f"{case.id}: descriptive ground_truth.{key} must be noted as descriptive in case.notes"
            )
