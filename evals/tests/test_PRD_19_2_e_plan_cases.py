"""Acceptance tests for E-PLAN eval cases (PRD 19.2; EV-02, EV-03, FR-INT-03, FR-INT-04, FR-INT-06)."""

import re
from urllib.parse import urlparse

from _evals_lib import REPO_ROOT
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_PLAN_FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures" / "plan"
_URL_RE = re.compile(r"https?://[^\s\"'<>)\],]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _e_plan_cases() -> list[Case]:
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == "E-PLAN"]


def _extract_hosts(text: str) -> list[str]:
    hosts = [urlparse(m.group(0)).hostname or "" for m in _URL_RE.finditer(text)]
    hosts.extend(m.group(1).lower() for m in _EMAIL_RE.finditer(text))
    return [h.lower().rstrip(".") for h in hosts if h]


def test_PRD_19_2_e_plan_loads_ten_cases_01_to_10():
    cases = _e_plan_cases()
    assert [c.id for c in cases] == [f"E-PLAN-{i:02d}" for i in range(1, 11)]
    for case in cases:
        assert case.status == "ready" and case.deploy_gate is False and case.recording is None
        assert case.ground_truth is not None
        assert case.ground_truth.get("brief_valid") is True
        assert case.ground_truth.get("approach_count") == 2.5
        assert case.notes and "EV-03" in case.notes
        checks = {
            (c["check"], c["args"].get("field"), c["args"].get("schema"), c["args"].get("tolerance"))
            for c in case.checks
        }
        assert ("schema_valid", "brief", "brief.schema.json", None) in checks
        assert ("schema_valid", "plan", "plan.schema.json", None) in checks
        assert ("equals_ground_truth", "approach_count", None, 0.5) in checks


def test_PRD_19_2_e_plan_clear_vague_and_file_tasks_match_ground_truth():
    cases = _e_plan_cases()
    assert len(cases) == 10
    clear = [c for c in cases if c.inputs.get("task_kind") == "clear"]
    vague = [c for c in cases if c.inputs.get("task_kind") == "vague"]
    with_files = [c for c in cases if c.inputs.get("task_kind") == "with_files"]
    assert len(clear) == 4 and len(vague) == 4 and len(with_files) == 2

    for case in clear:
        assert case.ground_truth is not None and case.ground_truth["question_count"] == 0
        assert len(case.scripted_answers) == 0

    for case in vague:
        assert case.ground_truth is not None and case.ground_truth["question_count"] == 2
        assert len(case.scripted_answers) == case.ground_truth["question_count"]
        assert all(ans.get("match") and ans.get("answer") for ans in case.scripted_answers)
        q_checks = [
            c for c in case.checks if c["check"] == "equals_ground_truth" and c["args"].get("field") == "question_count"
        ]
        assert len(q_checks) == 1 and q_checks[0]["args"].get("tolerance") == 1

    for case in with_files:
        files = case.inputs.get("files") or []
        assert len(files) >= 1
        assert case.ground_truth is not None
        assert len(case.scripted_answers) == case.ground_truth["question_count"]
        for rel in files:
            path = REPO_ROOT / rel
            assert path.is_file() and _PLAN_FIXTURES_DIR in path.resolve().parents
            assert path.read_text(encoding="utf-8").strip()


def test_PRD_19_2_e_plan_every_host_ends_in_example_or_invalid():
    cases = _e_plan_cases()
    assert len(cases) == 10
    texts = [c.path.read_text(encoding="utf-8") for c in cases]
    if _PLAN_FIXTURES_DIR.is_dir():
        texts.extend(p.read_text(encoding="utf-8") for p in sorted(_PLAN_FIXTURES_DIR.rglob("*")) if p.is_file())
    hosts = [h for text in texts for h in _extract_hosts(text)]
    assert hosts, "expected at least one fictional host in E-PLAN cases or fixtures"
    for host in hosts:
        assert host.endswith((".example", ".invalid")), f"non-fictional host found: {host}"
