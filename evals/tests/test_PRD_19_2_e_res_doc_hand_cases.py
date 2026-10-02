"""Acceptance tests for E-RES, E-DOC, and E-HAND eval cases (PRD 19.2, 19.4 gate 4; EV-01, EV-05, EV-10)."""

import csv
import re
import subprocess
import sys
from urllib.parse import urlparse

from conftest import REPO_ROOT
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_DOC_FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures" / "doc"
_SEEDS_DIR = REPO_ROOT / "services" / "sandbox-web" / "seed"
_URL_RE = re.compile(r"https?://[^\s\"'<>)\],]+")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_DENYLIST_BRANDS_RE = re.compile(
    r"\b(?:Google|Drive|Microsoft|Slack|Dropbox|Amazon|Apple|OpenAI|Yanmar|Pettit|Interlux|Wells\s+Fargo|GreenDot)\b",
    re.IGNORECASE,
)


def _group_cases(group: str) -> list[Case]:
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == group]


def _extract_hosts(text: str) -> list[str]:
    hosts = [urlparse(m.group(0)).hostname or "" for m in _URL_RE.finditer(text)]
    hosts.extend(m.group(1).lower() for m in _EMAIL_RE.finditer(text))
    return [h.lower().rstrip(".") for h in hosts if h]


def test_PRD_19_2_e_res_doc_hand_counts_are_10_6_and_20() -> None:
    res_cases = _group_cases("E-RES")
    doc_cases = _group_cases("E-DOC")
    hand_cases = _group_cases("E-HAND")
    assert [c.id for c in res_cases] == [f"E-RES-{i:02d}" for i in range(1, 11)]
    assert [c.id for c in doc_cases] == [f"E-DOC-{i:02d}" for i in range(1, 7)]
    assert [c.id for c in hand_cases] == [f"E-HAND-{i:02d}" for i in range(1, 21)]


def test_PRD_19_2_e_res_doc_hand_every_e_res_ground_truth_value_appears_verbatim_in_cited_seed() -> None:
    res_cases = _group_cases("E-RES")
    assert len(res_cases) == 10
    for case in res_cases:
        assert case.status == "ready"
        assert case.recording is None
        assert "EV-01" in case.measures and "EV-05" in case.measures
        seed_rel = case.inputs.get("seed")
        assert isinstance(seed_rel, str) and seed_rel.startswith("services/sandbox-web/seed/")
        seed_path = REPO_ROOT / seed_rel
        assert seed_path.is_file() and _SEEDS_DIR in seed_path.resolve().parents
        assert seed_path.name != "redteam-notes.yaml"
        seed_text = seed_path.read_text(encoding="utf-8")

        gt = case.ground_truth
        assert isinstance(gt, dict) and len(gt) >= 1
        for key, val in gt.items():
            assert str(val) in seed_text, f"{case.id}: ground_truth[{key!r}]={val!r} not verbatim in {seed_rel}"
            assert any(
                c.get("check") == "equals_ground_truth"
                and c.get("args", {}).get("field") == key
                and c.get("args", {}).get("tolerance") == 0
                for c in case.checks
            ), f"{case.id}: missing equals_ground_truth(tolerance=0) check for {key!r}"


def test_PRD_19_2_e_res_doc_hand_e_doc_sections_and_chart_values_equal_source_csv() -> None:
    doc_cases = _group_cases("E-DOC")
    assert len(doc_cases) == 6
    formats = [c.inputs.get("format") for c in doc_cases]
    assert formats.count("pdf") == 3 and formats.count("pptx") == 3

    for case in doc_cases:
        assert case.status == "skeleton"
        assert case.recording is None
        assert "FR-CON-09" in case.measures
        files = case.inputs.get("files") or []
        assert len(files) == 1
        csv_path = REPO_ROOT / files[0]
        assert csv_path.is_file() and _DOC_FIXTURES_DIR in csv_path.resolve().parents

        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) >= 3

        gt = case.ground_truth
        assert isinstance(gt, dict)
        req_sections = gt.get("required_sections")
        assert isinstance(req_sections, list) and len(req_sections) >= 3
        assert req_sections == case.inputs.get("required_sections")

        label_col = case.inputs.get("chart_label_column")
        value_col = case.inputs.get("chart_value_column")
        assert isinstance(label_col, str) and isinstance(value_col, str)
        expected_chart = {row[label_col]: int(row[value_col]) for row in rows}
        assert gt.get("chart_values") == expected_chart


def test_PRD_19_2_e_res_doc_hand_e_hand_twenty_cases_and_five_deploy_gates() -> None:
    hand_cases = _group_cases("E-HAND")
    assert len(hand_cases) == 20
    gate_cases = [c for c in hand_cases if c.deploy_gate is True]
    assert len(gate_cases) == 5, f"expected 5 E-HAND deploy_gate cases, got {len(gate_cases)}"

    for case in hand_cases:
        assert case.status == "skeleton"
        assert case.recording is None
        assert "EV-10" in case.measures and "FR-AGT-09" in case.measures
        assert case.ground_truth is not None
        assert case.ground_truth.get("rework") is False
        assert any(
            c.get("check") == "equals_ground_truth" and c.get("args", {}).get("field") == "rework" for c in case.checks
        )


def test_PRD_19_2_e_res_doc_hand_fictional_hosts_brands_and_secret_scan() -> None:
    cases = _group_cases("E-RES") + _group_cases("E-DOC") + _group_cases("E-HAND")
    assert len(cases) == 36
    fixture_files = sorted(p for p in _DOC_FIXTURES_DIR.rglob("*") if p.is_file())
    assert len(fixture_files) == 6

    all_paths = [c.path for c in cases] + fixture_files
    for path in all_paths:
        text = path.read_text(encoding="utf-8")
        m = _DENYLIST_BRANDS_RE.search(text)
        assert m is None, f"{path.name}: real brand {m.group(0)!r} found"
        for host in _extract_hosts(text):
            assert host.endswith((".example", ".invalid")), f"{path.name}: non-fictional host {host!r}"

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), *(str(p) for p in all_paths)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
