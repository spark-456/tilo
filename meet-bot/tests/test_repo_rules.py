"""Guards for the hard rules: selectors in one place, no class selectors, no password handling, no secrets."""

import re
from pathlib import Path

from bot import selectors as S
from bot.config import parse_dotenv

ROOT = Path(__file__).parent.parent
SRC = {p: p.read_text(encoding="utf-8") for p in (ROOT / "bot").glob("*.py")}


def test_every_selector_has_a_fallback_and_no_css_classes():
    assert len(S.ALL_SELECTORS) > 15
    for sel in S.ALL_SELECTORS:
        assert sel.strategies, sel.name
        for strat in sel.strategies:
            assert strat[0] in {"role", "text", "aria", "aria_region", "placeholder"}, sel.name
            assert not re.search(r"(^|\s)\.[A-Za-z]", strat[-1]), f"class-like selector in {sel.name}"
    multi = [s for s in S.ALL_SELECTORS if len(s.strategies) >= 2]
    assert len(multi) >= 10


def test_no_meet_selectors_outside_selectors_py():
    for path, text in SRC.items():
        if path.name in ("selectors.py", "captions.py"):  # captions.py holds the in-page observer's region query
            continue
        assert "aria-label*=" not in text.replace('[aria-label*="{strat[1]}" i]', ""), path.name
        assert 'get_by_role("button"' not in text, path.name


def test_no_password_anywhere():
    for path, text in SRC.items():
        assert not re.search(r"\.fill\(.*passw", text, re.I), path.name
        assert "PASSWORD" not in text.upper().replace("NOT AUTHENTICATION", "") or path.name == "main.py"
    env = parse_dotenv((ROOT / ".env.example").read_text(encoding="utf-8"))
    assert not any("PASS" in k.upper() for k in env)
    assert env["BOT_GOOGLE_EMAIL"] == "tiloagent@gmail.com" and env["GEMINI_API_KEY"] == ""


def test_dotenv_parsing():
    assert parse_dotenv('A=1\n# c\nB="x y"\n\nC=\n') == {"A": "1", "B": "x y", "C": ""}
