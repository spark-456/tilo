"""Acceptance tests for E-RES, E-DOC, and E-HAND eval cases (PRD 19.2)."""

import csv
import re
from typing import Any

import yaml
from _evals_lib import REPO_ROOT
from test_PRD_19_2_eval_set_structure import DENYLIST_BRANDS_RE, REAL_ROUTING_RE
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_GATE_TAG_RE = re.compile(r"\(gate\s*\d+\)", re.IGNORECASE)


_SEED_PATHS: dict[tuple[str, str], tuple[Any, ...]] = {
    ("E-RES-01", "plan_name"): ("ledgerly", "pages", "pricing", "plans", ("name", "Growth"), "name"),
    ("E-RES-01", "monthly"): ("ledgerly", "pages", "pricing", "plans", ("name", "Growth"), "monthly"),
    ("E-RES-01", "annual"): ("ledgerly", "pages", "pricing", "plans", ("name", "Growth"), "annual"),
    ("E-RES-01", "seats"): ("ledgerly", "pages", "pricing", "plans", ("name", "Growth"), "seats"),
    ("E-RES-02", "change_date"): ("ledgerly", "pages", "changelog", "entries", 0, "date"),
    ("E-RES-02", "old_growth_monthly"): ("ledgerly", "pages", "old-pricing", "plans", ("name", "Growth"), "monthly"),
    ("E-RES-02", "new_growth_monthly"): ("ledgerly", "pages", "pricing", "plans", ("name", "Growth"), "monthly"),
    ("E-RES-03", "basic_monthly"): ("beacontrack", "pages", "pricing", "plans", ("name", "Basic"), "monthly"),
    ("E-RES-03", "enterprise_monthly"): (
        "beacontrack",
        "pages",
        "pricing",
        "plans",
        ("name", "Enterprise"),
        "monthly",
    ),
    ("E-RES-03", "enterprise_seats"): ("beacontrack", "pages", "pricing", "plans", ("name", "Enterprise"), "seats"),
    ("E-RES-04", "lite_annual"): ("fluxpoint", "pages", "pricing", "plans", ("name", "Lite"), "annual"),
    ("E-RES-04", "team_annual"): ("fluxpoint", "pages", "pricing", "plans", ("name", "Team"), "annual"),
    ("E-RES-04", "business_annual"): ("fluxpoint", "pages", "pricing", "plans", ("name", "Business"), "annual"),
    ("E-RES-05", "ledgerly_growth_monthly"): ("ledgerly", "pages", "pricing", "plans", ("name", "Growth"), "monthly"),
    ("E-RES-05", "beacontrack_pro_monthly"): ("beacontrack", "pages", "pricing", "plans", ("name", "Pro"), "monthly"),
    ("E-RES-05", "fluxpoint_team_monthly"): ("fluxpoint", "pages", "pricing", "plans", ("name", "Team"), "monthly"),
    ("E-RES-06", "base_fee"): ("riverside-kitchens", "rate_card", "base_fee"),
    ("E-RES-06", "per_sqft"): ("riverside-kitchens", "rate_card", "per_sqft"),
    ("E-RES-06", "per_cabinet"): ("riverside-kitchens", "rate_card", "per_cabinet"),
    ("E-RES-06", "licence"): ("riverside-kitchens", "pages", "profile", "licence"),
    ("E-RES-07", "base_fee"): ("northgate-renovations", "rate_card", "base_fee"),
    ("E-RES-07", "per_sqft"): ("northgate-renovations", "rate_card", "per_sqft"),
    ("E-RES-07", "licence"): ("northgate-renovations", "pages", "profile", "licence"),
    ("E-RES-07", "insurance"): ("northgate-renovations", "pages", "profile", "insurance"),
    ("E-RES-08", "base_fee"): ("maple-stone-builders", "rate_card", "base_fee"),
    ("E-RES-08", "per_cabinet"): ("maple-stone-builders", "rate_card", "per_cabinet"),
    ("E-RES-08", "licence"): ("maple-stone-builders", "pages", "profile", "licence"),
    ("E-RES-08", "first_date"): ("maple-stone-builders", "pages", "profile", "availability", 0),
    ("E-RES-09", "riverside_per_sqft"): ("riverside-kitchens", "rate_card", "per_sqft"),
    ("E-RES-09", "northgate_per_sqft"): ("northgate-renovations", "rate_card", "per_sqft"),
    ("E-RES-09", "maple_stone_per_sqft"): ("maple-stone-builders", "rate_card", "per_sqft"),
    ("E-RES-10", "riverside_licence"): ("riverside-kitchens", "pages", "profile", "licence"),
    ("E-RES-10", "riverside_first_date"): ("riverside-kitchens", "pages", "profile", "availability", 0),
    ("E-RES-10", "northgate_licence"): ("northgate-renovations", "pages", "profile", "licence"),
    ("E-RES-10", "northgate_first_date"): ("northgate-renovations", "pages", "profile", "availability", 0),
}


def _resolve_seed_path(seeds: dict[str, Any], path: tuple[Any, ...]) -> Any:
    cur: Any = seeds[path[0]]
    for step in path[1:]:
        if isinstance(step, tuple):
            k, v = step
            cur = next(item for item in cur if isinstance(item, dict) and item.get(k) == v)
        else:
            cur = cur[step]
    return cur


def _group_cases(group: str) -> list[Case]:
    """The PRD 19.2 cases of a group: E-RES-11 is the ADR-0029 extra (LW-16, BQ-LW16-1) and has its own tests."""
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == group and c.id != "E-RES-11"]


def test_PRD_19_2_e_res_doc_hand_ten_e_res_cases_match_sandbox_web_seeds() -> None:
    cases = _group_cases("E-RES")
    assert [c.id for c in cases] == [f"E-RES-{i:02d}" for i in range(1, 11)]
    for case in cases:
        assert case.status == "ready"
        assert "EV-01" in case.measures and "EV-05" in case.measures
        seed_files = case.inputs.get("seed_files", [])
        assert seed_files, f"{case.id} must list seed_files"
        seeds: dict[str, Any] = {}
        for rel in seed_files:
            seed_data = yaml.safe_load((REPO_ROOT / rel).read_text(encoding="utf-8"))
            seeds[seed_data["slug"]] = seed_data
        assert case.ground_truth is not None and len(case.ground_truth) > 0
        for key, val in case.ground_truth.items():
            path = _SEED_PATHS.get((case.id, key))
            assert path is not None, f"{case.id}: missing seed lookup path for {key!r}"
            expected = _resolve_seed_path(seeds, path)
            assert val == expected and type(val) is type(expected), (
                f"{case.id}.{key}: ground_truth {val!r} != seed value {expected!r} at {path}"
            )
            assert {"check": "equals_ground_truth", "args": {"field": key, "tolerance": 0}} in case.checks
        assert {
            "check": "groundedness",
            "kind": "autorater",
            "args": {"field": "citations", "sources": case.inputs["seed_urls"]},
        } in case.checks
        assert case.notes and "EV-05" in case.notes and "autorater" in case.notes


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
        assert gt["files_open_cleanly"] is True
        assert {"check": "equals_ground_truth", "args": {"field": "files_open_cleanly"}} in case.checks
        checked_fields = {c["args"]["field"] for c in case.checks if c["check"] == "equals_ground_truth"}
        assert checked_fields == set(gt.keys()), f"{case.id}: checks {checked_fields} must cover all ground_truth keys"


def test_PRD_19_2_e_res_doc_hand_twenty_e_hand_cases_five_in_deploy_gate() -> None:
    cases = _group_cases("E-HAND")
    assert [c.id for c in cases] == [f"E-HAND-{i:02d}" for i in range(1, 21)]
    assert [c.id for c in cases if c.deploy_gate] == [f"E-HAND-{i:02d}" for i in range(1, 6)]
    for case in cases:
        assert case.status == "skeleton"
        assert "EV-10" in case.measures and "FR-AGT-09" in case.measures
        assert case.ground_truth == {"rework": False}
        assert {"check": "equals_ground_truth", "args": {"field": "rework"}} in case.checks
        assert case.notes and "synthetic placeholders" in case.notes and "CL-EVID" in case.notes


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
