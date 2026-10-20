"""FR-MTG-09 (live 20 Oct): Meet moves a joined call to /meet/<code>, hides its toolbar while idle, and its waiting
room also carries a Leave control, so "in the call" needs a meeting address and a control only a joined call has."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import selectors as S
from bot.browser import MeetBrowser

CALL = "https://meet.google.com/meet/abc-defg-hij"


def test_FR_MTG_09_LIVE_meeting_url_accepts_the_meet_prefix():
    assert S.MEETING_URL_RE.match("https://meet.google.com/abc-defg-hij").group(1) == "abc-defg-hij"
    assert S.MEETING_URL_RE.match("https://meet.google.com/meet/abc-defg-hij").group(1) == "abc-defg-hij"
    assert S.MEETING_URL_RE.match("https://meet.google.com/landing") is None


def _bot(visible: dict[str, bool], url: str = CALL) -> MeetBrowser:
    bot = MeetBrowser.__new__(MeetBrowser)
    bot.page = SimpleNamespace(url=url, mouse=SimpleNamespace(move=AsyncMock()))
    bot.visible = AsyncMock(side_effect=lambda sel: visible.get(sel.name, False))
    return bot


def _attached(monkeypatch, names: set[str]) -> None:
    import bot.browser as B

    def locate(page, strat):
        return SimpleNamespace(count=AsyncMock(return_value=1 if strat[-1] in names else 0))

    monkeypatch.setattr(B, "locate", locate)


def test_FR_MTG_09_LIVE_in_call_counts_a_hidden_chat_button(monkeypatch):
    _attached(monkeypatch, {"Chat with everyone"})
    assert asyncio.run(_bot({}).in_call()) is True


def test_FR_MTG_09_LIVE_lobby_is_not_in_call(monkeypatch):
    _attached(monkeypatch, {"Chat with everyone"})
    assert asyncio.run(_bot({"waiting_text": True}).in_call()) is False


def test_FR_MTG_09_LIVE_a_leave_control_alone_is_not_in_call(monkeypatch):
    _attached(monkeypatch, {"Leave call"})
    assert asyncio.run(_bot({}).in_call()) is False


def test_FR_MTG_09_LIVE_meet_home_is_not_in_call(monkeypatch):
    _attached(monkeypatch, {"Chat with everyone"})
    assert asyncio.run(_bot({}, url="https://meet.google.com/home").in_call()) is False


def test_FR_MTG_09_LIVE_new_lobby_wording_is_waiting():
    import re

    text = "Please wait until a meeting host brings you into the call"
    assert any(re.search(s[1], text, re.I) for s in S.WAITING_TEXT.strategies)
