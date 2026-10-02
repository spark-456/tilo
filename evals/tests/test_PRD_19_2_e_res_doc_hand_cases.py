"""Acceptance tests for E-RES, E-DOC, and E-HAND eval cases (PRD 19.2)."""

import csv
import re
from typing import Any

import yaml
from conftest import REPO_ROOT
from test_PRD_19_2_eval_set_structure import DENYLIST_BRANDS_RE, REAL_ROUTING_RE
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_GATE_TAG_RE = re.compile(r"\(gate\s*\d+\)", re.IGNORECASE)


def _all_scalars(value: Any) -> set[str]:
    if isinstance(value, dict):
        return {s for v in value.values() for s in _all_scalars(v)}
    if isinstance(value, list):
        return {s for v in value for s in _all_scalars(v)}
    return set() if value is None else {str(value)}


def _group_cases(group: str) -> list[Case]:
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == group]


def test_PRD_19_2_e_res_doc_hand_ten_e_res_cases_match_sandbox_web_seeds() -> None:
    cases = _group_cases("E-RES")
    assert [c.id for c in cases] == [f"E-RES-{i:02d}" for i in range(1, 11)]
    for case in cases:
        assert case.status == "ready"
        assert "EV-01" in case.measures and "EV-05" in case.measures
        seed_files = case.inputs.get("seed_files", [])
        assert seed_files, f"{case.id} must list seed_files"
        scalars: set[str] = set()
        for rel in seed_files:
            seed_data = yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))
            scalars |= _all_scalars(seed_data)
        assert case.ground_truth is not None and len(case.ground_truth) > 0
        for key, val in case.ground_truth.items():
            assert str(val) in scalars, f"{case.id}: field {key}={val!r} not in seed scalars"
            assert {"check": "equals_ground_truth", "args": {"field": key, "tolerance": 0}} in case.checks


def test_PRD_19_2_e_res_doc_hand_six_e_doc_cases_match_csv_fixtures() -> None:
    cases = _group_cases("E-DOC")
    assert [c.id for c in cases] == [f"E-DOC-{i:02d}" for i in range(1, 7)]
    formats = [c.inputs.get("format") for c in cases]
    assert formats.count("pdf") == 3 and formats.count("pptx") == 3
    for case in cases:
        assert case.status == "skeleton" and case.deploy_gate is False
        assert "FR-CON-09" in case.measures and "FR-CON-10" in case.measures
        rel_fixture = case.inputs["table_fixture"]
        fixture_path = REPO_ROOT / rel_fixture
        with fixture_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        metric_col = case.inputs["metric_column"]
        group_col = case.inputs["group_column"]
        label_col = case.inputs["label_column"]
        total = sum(int(r[metric_col]) for r in rows)
        by_group: dict[str, int] = {}
        for r in rows:
            g = r[group_col]
            by_group[g] = by_group.get(g, 0) + int(r[metric_col])
        max_row = max(rows, key=lambda r: int(r[metric_col]))
        chart_values = [int(r[metric_col]) for r in rows]
        gt = case.ground_truth
        assert gt is not None
        assert gt["required_sections"] == case.inputs["required_sections"]
        assert gt["chart_values"] == chart_values
        assert gt["row_count"] == len(rows)
        assert gt["total"] == total
        assert gt["by_group"] == by_group
        assert gt["max_row_label"] == max_row[label_col]
        assert gt["max_row_value"] == int(max_row[metric_col])
        checked_fields = {c["args"]["field"] for c in case.checks if c["check"] == "equals_ground_truth"}
        assert checked_fields == set(gt.keys()), f"{case.id}: checks {checked_fields} must cover all ground_truth keys"


def test_PRD_19_2_e_res_doc_hand_twenty_e_hand_cases_five_in_deploy_gate() -> None:
    cases = _group_cases("E-HAND")
    assert [c.id for c in cases] == [f"E-HAND-{i:02d}" for i in range(1, 21)]
    assert sum(1 for c in cases if c.deploy_gate) == 5
    for case in cases:
        assert case.status == "skeleton"
        assert "EV-10" in case.measures and "FR-AGT-09" in case.measures
        assert case.ground_truth == {"rework": False}
        assert {"check": "equals_ground_truth", "args": {"field": "rework"}} in case.checks


def test_PRD_19_2_e_res_doc_hand_brand_and_routing_denylist() -> None:
    cases = _group_cases("E-RES") + _group_cases("E-DOC") + _group_cases("E-HAND")
    assert len(cases) == 36
    for case in cases:
        assert _GATE_TAG_RE.search(case.title) is None, f"{case.id}: gate tag in title {case.title!r}"
    doc_fixtures = REPO_ROOT / "evals" / "fixtures" / "doc"
    fixture_files = sorted(p for p in doc_fixtures.rglob("*") if p.is_file())
    assert len(fixture_files) == 6

    all_paths = [c.path for c in cases] + fixture_files
    for path in all_paths:
        text = path.read_text(encoding="utf-8")
        brand_match = DENYLIST_BRANDS_RE.search(f"{path.name}\n{text}")
        assert brand_match is None, f"{path.name}: real brand {brand_match.group(0)!r} found"
        routing_match = REAL_ROUTING_RE.search(text)
        assert routing_match is None, f"{path.name}: routing/account number {routing_match.group(0)!r} found"
