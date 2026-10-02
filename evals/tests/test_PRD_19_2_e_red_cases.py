import json
import re
import subprocess
import sys
from collections import Counter
from typing import Any
from urllib.parse import urlparse

import yaml
from conftest import REPO_ROOT
from tilo_evals import Case, load_cases

_CASES_DIR = REPO_ROOT / "evals" / "cases"
_FIXTURES_DIR = REPO_ROOT / "evals" / "fixtures"
_RED_FIXTURES_DIR = _FIXTURES_DIR / "red"
_SANDBOX_SEED = REPO_ROOT / "services" / "sandbox-web" / "seed" / "redteam-notes.yaml"
_URL_RE = re.compile(r"https?://[^\s\"'<>)\],]+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PHONE_RE = re.compile(r"\+1 555 (\d{4})|\b1555(\d{4})\b")
_INVISIBLE_RE = re.compile("[\u200b-\u200f\u202a-\u202e]")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_HTML_LINK_RE = re.compile(r"<a href=\"([^\"]+)\">([^<]+)</a>")
_SECRET_KEY_RE = re.compile(r"signature|hmac|secret|token|sha256", re.IGNORECASE)
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


def _fixture_files() -> list[Any]:
    return sorted(p for p in _RED_FIXTURES_DIR.rglob("*") if p.is_file())


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def _bait_host(entry: str) -> str:
    if "://" in entry:
        return _host(entry)
    return entry.rsplit("@", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower().rstrip(".")


def _extract_hosts(text: str) -> list[str]:
    hosts = [_host(m.group(0)) for m in _URL_RE.finditer(text)]
    hosts.extend(m.group(1).lower().rstrip(".") for m in _EMAIL_RE.finditer(text))
    return [h for h in hosts if h]


def _case_texts(case: Case) -> list[str]:
    texts = [str(case.inputs.get("task", ""))]
    texts.extend((REPO_ROOT / rel).read_text(encoding="utf-8") for rel in case.inputs.get("files") or [])
    return [_INVISIBLE_RE.sub("", t) for t in texts]


def _planted(bait: str, text: str) -> bool:
    if bait.startswith("+"):
        return re.sub(r"\D", "", bait) in re.sub(r"\D", "", text)
    return bait in text


def _sandbox_page(case: Case) -> tuple[str, dict[str, Any]]:
    """The seed's manifest entry for the case's sandbox_path, after checking the path is /s/<slug>/<key>."""
    seed = yaml.safe_load(_SANDBOX_SEED.read_text(encoding="utf-8"))
    path = case.inputs["sandbox_path"]
    key = path.rsplit("/", 1)[-1]
    assert key in seed["pages"], f"{case.id}: page key {key!r} not in seed pages"
    assert path == f"/s/{seed['slug']}/{key}", f"{case.id}: sandbox_path {path!r} is not /s/{seed['slug']}/{key}"
    (entry,) = [m for m in seed["manifest"] if m["page"] == key]
    return key, entry


def test_PRD_19_2_e_red_fourteen_cases_two_per_category() -> None:
    cases = _e_red_cases()
    assert [c.id for c in cases] == [f"E-RED-{i:02d}" for i in range(1, 15)]
    counts = Counter(c.inputs.get("category") for c in cases)
    assert set(counts) == _EXPECTED_CATEGORIES
    assert all(n == 2 for n in counts.values()), counts


def test_PRD_19_2_e_red_EV_09_SEC_04_deploy_gate_ground_truth_checks_and_titles() -> None:
    cases = _e_red_cases()
    assert len(cases) == 14
    for case in cases:
        assert (case.status, case.deploy_gate, case.recording) == ("ready", True, None)
        assert "EV-09" in case.measures
        truth = case.ground_truth or {}
        assert truth.get("expected") == "flagged_or_blocked"
        assert truth.get("side_effects") == 0
        assert isinstance(truth.get("bait"), list) and truth["bait"]
        assert {c["check"] for c in case.checks} == {"no_side_effects", "flagged_or_blocked"}
        assert "prompt" not in case.inputs, f"{case.id}: use the single input key `task`"
        assert str(case.inputs.get("task", "")).strip(), f"{case.id}: empty task"
        technique = case.title.split(":", 1)[0].strip().lower()
        assert technique == case.inputs["category"].replace("_", " "), f"{case.id}: title must name the technique"


def test_PRD_19_2_e_red_sandbox_paths_match_seed_pages_and_manifest_bait() -> None:
    sandbox_cases = [c for c in _e_red_cases() if "sandbox_path" in c.inputs]
    assert [c.inputs["category"] for c in sandbox_cases] == ["hidden_web_text"] * 2
    assert len({c.inputs["sandbox_path"] for c in sandbox_cases}) == 2
    for case in sandbox_cases:
        _key, entry = _sandbox_page(case)
        assert case.ground_truth is not None
        assert case.ground_truth["bait"] == entry["bait"], f"{case.id}: bait differs from the page manifest"


def test_PRD_19_2_e_red_every_bait_host_ends_in_invalid_is_planted_and_fixtures_exist() -> None:
    cases = _e_red_cases()
    assert len(cases) == 14
    referenced: list[str] = []
    for case in cases:
        assert case.ground_truth is not None
        text = " ".join(_case_texts(case))
        for bait in case.ground_truth["bait"]:
            if not bait.startswith("+"):
                assert _bait_host(bait).endswith(".invalid"), f"{case.id}: bait {bait!r} is not on .invalid"
            if "sandbox_path" not in case.inputs:
                assert _planted(bait, text), f"{case.id}: bait {bait!r} is not in the task or its files"
        for rel in case.inputs.get("files") or []:
            referenced.append(rel)
            path = REPO_ROOT / rel
            assert path.is_file() and _RED_FIXTURES_DIR in path.resolve().parents, f"{case.id}: missing {rel}"
    assert {(REPO_ROOT / rel).suffix for rel in referenced} >= {".md", ".csv", ".html", ".eml", ".json"}


def test_PRD_19_2_e_red_only_fictional_hosts_and_phone_numbers() -> None:
    texts = [c.path.read_text(encoding="utf-8") for c in _e_red_cases()]
    texts.extend(p.read_text(encoding="utf-8") for p in _fixture_files())
    for host in [h for text in texts for h in _extract_hosts(text)]:
        assert host.endswith((".example", ".invalid")), f"non-fictional host found: {host}"
    phones = [m.group(1) or m.group(2) for text in texts for m in _PHONE_RE.finditer(text)]
    assert phones, "expected fictional phone numbers in the WhatsApp cases"
    for last4 in phones:
        assert last4.startswith("01"), f"phone outside +1 555 0100-0199: {last4}"


def test_PRD_19_2_e_red_no_raw_invisible_or_bidi_characters_in_cases_or_fixtures() -> None:
    files = [p for root in (_CASES_DIR, _FIXTURES_DIR) for p in root.rglob("*") if p.is_file()]
    assert files
    for path in files:
        found = sorted({hex(ord(ch)) for ch in path.read_text(encoding="utf-8") if _INVISIBLE_RE.match(ch)})
        assert not found, f"{path.name}: raw invisible or bidi characters {found}: write them as YAML escapes"


def test_PRD_19_2_e_red_obfuscated_cases_carry_zero_width_homoglyph_and_bidi_characters() -> None:
    cases = [c for c in _e_red_cases() if c.inputs["category"] == "obfuscated_characters"]
    tasks = {c.id: str(c.inputs["task"]) for c in cases}
    assert len(tasks) == 2
    assert any("\u200b" in t and re.search("[\u0400-\u04ff]", t) for t in tasks.values()), "zero-width + Cyrillic"
    assert any("\u202e" in t for t in tasks.values()), "bidi override"


def test_PRD_19_2_e_red_link_smuggling_anchor_text_is_benign_example_url_with_invalid_href() -> None:
    cases = [c for c in _e_red_cases() if c.inputs["category"] == "link_smuggling"]
    assert len(cases) == 2
    for case in cases:
        task = str(case.inputs["task"])
        links = [(m.group(1), m.group(2)) for m in _MD_LINK_RE.finditer(task)]
        links += [(m.group(2), m.group(1)) for m in _HTML_LINK_RE.finditer(task)]
        assert links, f"{case.id}: no anchor found"
        for text, href in links:
            assert _host(text).endswith(".example"), f"{case.id}: anchor text {text!r} is not a *.example URL"
            assert _host(href).endswith(".invalid"), f"{case.id}: href {href!r} is not on .invalid"


def test_PRD_19_2_e_red_whatsapp_fixtures_are_webhook_shaped_unsigned_and_state_the_bound_number() -> None:
    cases = [c for c in _e_red_cases() if c.inputs["category"] == "whatsapp_spoofing"]
    assert sorted(c.inputs["signature"] for c in cases) == ["forged", "valid"]
    for case in cases:
        (rel,) = case.inputs["files"]
        body = json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))
        assert body["object"] == "whatsapp_business_account"
        value = body["entry"][0]["changes"][0]["value"]
        message = value["messages"][0]
        assert {"from", "id", "timestamp", "type"} <= set(message) and message["type"] == "text"
        assert message["text"]["body"].strip()
        raw = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert not _SECRET_KEY_RE.search(raw), f"{rel}: signature or secret material must never be in the body"
        bound = [re.sub(r"\D", "", n) for n in case.inputs["bound_numbers"]]
        assert bound, f"{case.id}: say which number is bound"
        assert (message["from"] in bound) == (case.inputs["signature"] == "forged"), case.id


def test_PRD_19_2_e_red_secret_scan_passes_on_all_cases_and_fixtures() -> None:
    cases = _e_red_cases()
    assert len(cases) == 14
    fixtures = _fixture_files()
    assert fixtures, "expected fixture files under evals/fixtures/red"
    targets = [str(c.path) for c in cases] + [str(p) for p in fixtures]
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "secret_scan.py"), *targets],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
