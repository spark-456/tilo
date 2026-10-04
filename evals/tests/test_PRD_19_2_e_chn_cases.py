import re
import subprocess
import sys
from collections import Counter
from urllib.parse import urlparse

from conftest import REPO_ROOT
from test_PRD_19_2_eval_set_structure import DENYLIST_BRANDS_RE, REAL_ROUTING_RE
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_URL_RE = re.compile(r"https?://[^\s\"'<>)\],]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"\+1 555 (\d{4})")
_EXPECTED_CATEGORIES = {
    "small_talk",
    "general_knowledge_or_homework",
    "medical_legal_or_financial_advice",
    "requests_for_another_person_data",
    "general_chatbot_or_another_app",
    "change_settings_or_policies",
}


def _e_chn_cases() -> list[Case]:
    return [c for c in load_cases(str(_CASES_DIR)) if c.group == "E-CHN"]


def _extract_hosts(text: str) -> list[str]:
    hosts = [urlparse(m.group(0)).hostname or "" for m in _URL_RE.finditer(text)]
    hosts.extend(m.group(1).lower() for m in _EMAIL_RE.finditer(text))
    return [h.lower().rstrip(".") for h in hosts if h]


def _extract_phones(text: str) -> list[str]:
    return [m.group(0) for m in _PHONE_RE.finditer(text)]


def test_PRD_19_2_e_chn_thirty_cases_five_per_category() -> None:
    cases = _e_chn_cases()
    assert [c.id for c in cases] == [f"E-CHN-{i:02d}" for i in range(1, 31)]
    counts = Counter(c.inputs.get("category") for c in cases)
    assert set(counts.keys()) == _EXPECTED_CATEGORIES
    for cat, count in counts.items():
        assert count == 5, f"expected 5 cases for {cat}, got {count}"


def test_PRD_19_2_e_chn_FR_CHN_04_deploy_gate_ground_truth_and_checks() -> None:
    cases = _e_chn_cases()
    assert len(cases) == 30
    for case in cases:
        assert case.status == "skeleton"
        assert case.deploy_gate is False
        assert case.recording is None
        assert "FR-CHN-04" in case.measures
        assert case.notes and "FR-CHN-04" in case.notes and "descriptive" in case.notes
        assert case.checks == [
            {"check": "no_side_effects", "args": {}},
            {"check": "equals_ground_truth", "args": {"field": "expected"}},
            {"check": "equals_ground_truth", "args": {"field": "category"}},
        ]
        assert case.ground_truth is not None
        assert case.ground_truth.get("expected") == "redirect"
        assert case.ground_truth.get("category") == case.inputs.get("category")
        must_not = case.ground_truth.get("must_not")
        assert isinstance(must_not, str) and len(must_not) > 10


def test_PRD_19_2_e_chn_inputs_senders_and_tasks_valid() -> None:
    cases = _e_chn_cases()
    assert len(cases) == 30
    for case in cases:
        assert case.inputs.get("channel") == "whatsapp"
        assert case.inputs.get("bound") is True
        sender = case.inputs.get("sender")
        assert isinstance(sender, str)
        m = _PHONE_RE.fullmatch(sender)
        assert m is not None, f"{case.id}: sender {sender!r} not matching +1 555 01xx"
        num = int(m.group(1))
        assert 100 <= num <= 199, f"{case.id}: sender number {num} not in 0100..0199"

        msg = case.inputs.get("message")
        assert isinstance(msg, str) and len(msg.strip()) >= 20, f"{case.id}: hollow message"
        assert " ," not in msg and not re.search(r"(?<!\d),000\b", msg), (
            f"{case.id}: shell-expansion artifact in {msg!r}"
        )

        task = case.inputs.get("task")
        assert isinstance(task, str) and len(task.strip()) >= 20, f"{case.id}: missing/hollow task"


def test_PRD_19_2_e_chn_ground_truth_matches_planted_message() -> None:
    cases = _e_chn_cases()
    assert len(cases) == 30
    for case in cases:
        gt = case.ground_truth or {}
        keywords = gt.get("topic_keywords")
        assert isinstance(keywords, list) and len(keywords) >= 1, f"{case.id}: missing topic_keywords"
        msg_lower = case.inputs.get("message", "").lower()
        for kw in keywords:
            assert kw.lower() in msg_lower, f"{case.id}: topic keyword {kw!r} not found in message"


def test_PRD_19_2_e_chn_fictional_hosts_brands_and_secret_scan() -> None:
    cases = _e_chn_cases()
    assert len(cases) == 30
    texts = [c.path.read_text(encoding="utf-8") for c in cases]
    for case, text in zip(cases, texts, strict=True):
        m = DENYLIST_BRANDS_RE.search(text)
        assert m is None, f"{case.id}: real brand {m.group(0)!r} found"
        routing_match = REAL_ROUTING_RE.search(text)
        assert routing_match is None, f"{case.id}: routing/account number {routing_match.group(0)!r} found"
    for host in [h for text in texts for h in _extract_hosts(text)]:
        assert host.endswith((".example", ".invalid")), f"non-fictional host found: {host}"
    for phone in [p for text in texts for p in _extract_phones(text)]:
        assert phone.startswith("+1 555 01"), f"phone not in +1 555 0100-0199: {phone}"

    targets = [str(c.path) for c in cases]
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), *targets],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
