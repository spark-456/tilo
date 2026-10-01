"""Acceptance tests for E-RED red-team eval cases (PRD 19.2 E-RED, EV-09, SEC-04, PRD 19.4 gate 3)."""

import re
import subprocess
import sys
from collections import Counter
from urllib.parse import urlparse

from conftest import REPO_ROOT
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_RED_FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures" / "red"
_URL_RE = re.compile(r"https?://[^\s\"'<>)\],]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_EXPECTED_CATEGORIES = {
    "hidden_web_text",
    "document_injection",
    "email_injection",
    "exfiltration_bait",
    "whatsapp_spoofing",
    "link_smuggling",
    "obfuscated_characters",
}


def _e_red_cases() -> list[Case]:
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == "E-RED"]


def _bait_host(entry: str) -> str:
    if "://" in entry:
        return (urlparse(entry).hostname or "").lower().rstrip(".")
    return entry.rsplit("@", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower().rstrip(".")


def _extract_hosts(text: str) -> list[str]:
    hosts = [urlparse(m.group(0)).hostname or "" for m in _URL_RE.finditer(text)]
    hosts.extend(m.group(1).lower() for m in _EMAIL_RE.finditer(text))
    return [h.lower().rstrip(".") for h in hosts if h]


def test_PRD_19_2_e_red_fourteen_cases_two_per_category() -> None:
    cases = _e_red_cases()
    assert [c.id for c in cases] == [f"E-RED-{i:02d}" for i in range(1, 15)]
    counts = Counter(c.inputs.get("category") for c in cases)
    assert set(counts.keys()) == _EXPECTED_CATEGORIES
    for category, count in counts.items():
        assert count == 2, f"expected 2 cases for {category}, got {count}"


def test_PRD_19_2_e_red_EV_09_SEC_04_deploy_gate_ground_truth_and_checks() -> None:
    cases = _e_red_cases()
    assert len(cases) == 14
    for case in cases:
        assert case.status == "ready"
        assert case.deploy_gate is True
        assert case.recording is None
        assert "EV-09" in case.measures
        assert case.ground_truth is not None
        assert case.ground_truth.get("expected") == "flagged_or_blocked"
        assert case.ground_truth.get("side_effects") == 0
        bait = case.ground_truth.get("bait")
        assert isinstance(bait, list) and len(bait) >= 1
        check_names = [c["check"] for c in case.checks]
        assert "no_side_effects" in check_names
        assert "flagged_or_blocked" in check_names


def test_PRD_19_2_e_red_every_bait_host_ends_in_invalid_and_fixtures_exist() -> None:
    cases = _e_red_cases()
    assert len(cases) == 14
    referenced_files: list[str] = []
    for case in cases:
        assert case.ground_truth is not None
        for bait_entry in case.ground_truth["bait"]:
            host = _bait_host(str(bait_entry))
            assert host.endswith(".invalid"), f"{case.id}: bait host {host!r} does not end in .invalid"
        for rel in case.inputs.get("files") or []:
            referenced_files.append(rel)
            path = REPO_ROOT / rel
            assert path.is_file() and _RED_FIXTURES_DIR in path.resolve().parents, f"{case.id}: missing {rel}"
            assert path.read_text(encoding="utf-8").strip()

    assert referenced_files, "expected referenced red-team fixture files"
    exts = {(REPO_ROOT / rel).suffix for rel in referenced_files}
    assert {".md", ".csv", ".html", ".eml", ".json"} <= exts

    texts = [c.path.read_text(encoding="utf-8") for c in cases]
    texts.extend(p.read_text(encoding="utf-8") for p in sorted(_RED_FIXTURES_DIR.rglob("*")) if p.is_file())
    for host in [h for text in texts for h in _extract_hosts(text)]:
        assert host.endswith((".example", ".invalid")), f"non-fictional host found: {host}"


def test_PRD_19_2_e_red_secret_scan_passes_on_all_cases_and_fixtures() -> None:
    cases = _e_red_cases()
    assert len(cases) == 14
    fixture_files = sorted(p for p in _RED_FIXTURES_DIR.rglob("*") if p.is_file())
    assert fixture_files, "expected fixture files under evals/fixtures/red"
    targets = [str(c.path) for c in cases] + [str(p) for p in fixture_files]
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), *targets],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
