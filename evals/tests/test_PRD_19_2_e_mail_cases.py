"""Acceptance tests for E-MAIL eval cases (PRD 19.2, 19.4 gate 5; FR-CHN-09, FR-CHN-10, FR-CHN-12)."""

import re
import subprocess
import sys
from collections import Counter
from urllib.parse import urlparse

from conftest import REPO_ROOT
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\],]+")
_EXPECTED_CATEGORIES = {
    "needs_reply",
    "needs_action",
    "fyi",
    "newsletter_promo",
    "suspicious",
}


def _e_mail_cases() -> list[Case]:
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == "E-MAIL"]


def _extract_emails(text: str) -> list[str]:
    return [m.group(0).lower() for m in _EMAIL_RE.finditer(text)]


def _extract_hosts(text: str) -> list[str]:
    hosts = [urlparse(m.group(0)).hostname or "" for m in _URL_RE.finditer(text)]
    hosts.extend(m.group(1).lower() for m in _EMAIL_RE.finditer(text))
    return [h.lower().rstrip(".") for h in hosts if h]


def _thread_participants(thread: dict) -> set[str]:
    participants: set[str] = set()
    for msg in thread.get("messages", []):
        if sender := msg.get("from"):
            participants.add(sender.lower())
        for r in msg.get("to", []):
            participants.add(r.lower())
        for c in msg.get("cc", []):
            participants.add(c.lower())
    return participants


def test_PRD_19_2_e_mail_fifty_cases_total() -> None:
    cases = _e_mail_cases()
    assert len(cases) == 50
    assert [c.id for c in cases] == [f"E-MAIL-{i:02d}" for i in range(1, 51)]
    for c in cases:
        assert c.group == "E-MAIL"
        assert c.recording is None
        assert isinstance(c.title, str) and len(c.title.strip()) > 10


def test_PRD_19_2_e_mail_FR_CHN_09_triage_thirty_cases_six_per_category() -> None:
    cases = _e_mail_cases()
    triage_cases = [c for c in cases if c.id <= "E-MAIL-30"]
    assert len(triage_cases) == 30
    counts = Counter(c.ground_truth.get("category") for c in triage_cases if c.ground_truth)
    assert set(counts.keys()) == _EXPECTED_CATEGORIES
    for cat, count in counts.items():
        assert count == 6, f"expected 6 cases for {cat}, got {count}"

    for case in triage_cases:
        assert case.status == "ready"
        assert case.deploy_gate is False
        assert "FR-CHN-09" in case.measures
        gt = case.ground_truth or {}
        assert gt.get("priority") in {"high", "normal", "low"}
        checks = case.checks
        assert any(
            c.get("check") == "equals_ground_truth" and c.get("args", {}).get("field") == "category" for c in checks
        )


def test_PRD_19_2_e_mail_FR_CHN_10_drafting_twenty_cases_and_deploy_gates() -> None:
    cases = _e_mail_cases()
    drafting_cases = [c for c in cases if c.id > "E-MAIL-30"]
    assert len(drafting_cases) == 20
    gates = [c for c in drafting_cases if c.deploy_gate is True]
    assert len(gates) == 10, f"expected exactly 10 deploy_gate cases, got {len(gates)}"

    for case in drafting_cases:
        assert case.status == "skeleton"
        assert "FR-CHN-10" in case.measures
        assert "FR-CHN-12" in case.measures
        gt = case.ground_truth or {}
        assert isinstance(gt.get("allowed_recipients"), list) and len(gt["allowed_recipients"]) >= 1
        assert isinstance(gt.get("forbidden_commitments"), list) and len(gt["forbidden_commitments"]) >= 1

        check_names = {c.get("check"): c for c in case.checks}
        assert "recipients_within" in check_names
        assert "no_invented_commitments" in check_names
        assert "style_rubric" in check_names

        rec_check = check_names["recipients_within"]
        assert rec_check.get("args", {}).get("field") == "recipients"
        assert check_names["no_invented_commitments"].get("kind") == "autorater"
        assert check_names["style_rubric"].get("kind") == "autorater"


def test_PRD_19_2_e_mail_FR_CHN_12_allowlist_matches_thread_participants() -> None:
    cases = _e_mail_cases()
    drafting_cases = [c for c in cases if c.id > "E-MAIL-30"]
    for case in drafting_cases:
        thread = case.inputs.get("thread", {})
        participants = _thread_participants(thread)
        assert len(participants) >= 1, f"{case.id}: empty thread participants"

        gt_allowed = set(r.lower() for r in case.ground_truth.get("allowed_recipients", []))
        assert gt_allowed == participants, f"{case.id}: ground truth allowed_recipients does not match thread"

        rec_check = next(c for c in case.checks if c.get("check") == "recipients_within")
        check_allowlist = set(r.lower() for r in rec_check.get("args", {}).get("allowlist", []))
        assert check_allowlist == participants, f"{case.id}: check allowlist does not match thread"


def test_PRD_19_2_e_mail_ground_truth_matches_planted_content() -> None:
    cases = _e_mail_cases()
    for case in cases:
        task = case.inputs.get("task", "")
        assert isinstance(task, str) and len(task.strip()) >= 20, f"{case.id}: hollow task"
        thread = case.inputs.get("thread", {})
        messages = thread.get("messages", [])
        assert len(messages) >= 1, f"{case.id}: thread has no messages"
        for msg in messages:
            assert len(msg.get("subject", "").strip()) >= 5, f"{case.id}: hollow subject"
            assert len(msg.get("body", "").strip()) >= 30, f"{case.id}: hollow body"

        if case.id > "E-MAIL-30":
            instruction = case.inputs.get("instruction", "")
            assert isinstance(instruction, str) and len(instruction.strip()) >= 15, f"{case.id}: hollow instruction"
            forbidden = case.ground_truth.get("forbidden_commitments", [])
            for item in forbidden:
                assert item.lower() not in instruction.lower(), (
                    f"{case.id}: forbidden commitment {item!r} found in user instruction"
                )


def test_PRD_19_2_e_mail_all_addresses_end_in_example_and_secret_scan() -> None:
    cases = _e_mail_cases()
    texts = [c.path.read_text(encoding="utf-8") for c in cases]
    for email in [e for text in texts for e in _extract_emails(text)]:
        assert email.endswith(".example"), f"email address not ending in .example: {email}"
    for host in [h for text in texts for h in _extract_hosts(text)]:
        assert host.endswith((".example", ".invalid")), f"host not ending in .example or .invalid: {host}"

    targets = [str(c.path) for c in cases]
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), *targets],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
