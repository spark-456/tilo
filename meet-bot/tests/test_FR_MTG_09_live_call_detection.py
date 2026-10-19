"""FR-MTG-09 (live 20 Oct): Meet moves a joined call to /meet/<code> and hides its toolbar while idle."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot import selectors as S
from bot.browser import MeetBrowser


def test_FR_MTG_09_LIVE_meeting_url_accepts_the_meet_prefix():
    assert S.MEETING_URL_RE.match("https://meet.google.com/abc-defg-hij").group(1) == "abc-defg-hij"
    assert S.MEETING_URL_RE.match("https://meet.google.com/meet/abc-defg-hij").group(1) == "abc-defg-hij"
    assert S.MEETING_URL_RE.match("https://meet.google.com/landing") is None


def _bot(visible: dict[str, bool], attached: int) -> MeetBrowser:
    bot = MeetBrowser.__new__(MeetBrowser)
    bot.page = SimpleNamespace(mouse=SimpleNamespace(move=AsyncMock()))
    bot.visible = AsyncMock(side_effect=lambda sel: visible.get(sel.name, False))
    return bot, attached


def test_FR_MTG_09_LIVE_in_call_counts_a_hidden_leave_button(monkeypatch):
    import bot.browser as B

    bot, _ = _bot({}, 1)
    monkeypatch.setattr(B, "locate", lambda page, strat: SimpleNamespace(count=AsyncMock(return_value=1)))
    assert asyncio.run(bot.in_call()) is True


def test_FR_MTG_09_LIVE_lobby_is_not_in_call(monkeypatch):
    import bot.browser as B

    bot, _ = _bot({"waiting_text": True}, 1)
    monkeypatch.setattr(B, "locate", lambda page, strat: SimpleNamespace(count=AsyncMock(return_value=1)))
    assert asyncio.run(bot.in_call()) is False


def test_FR_MTG_09_LIVE_no_leave_control_is_not_in_call(monkeypatch):
    import bot.browser as B

    bot, _ = _bot({}, 0)
    monkeypatch.setattr(B, "locate", lambda page, strat: SimpleNamespace(count=AsyncMock(return_value=0)))
    assert asyncio.run(bot.in_call()) is False
