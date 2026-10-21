"""Owner's live call 21 Oct 22:10 IST (bot 00041): Tilo joined at 16:41:00 but posted its intro, and so started
listening, only at 16:41:40 (other calls that day: 4 s). Meet showed "Others may see your video differently" right after
the join; the one click that opens the chat panel landed while that card was up and was swallowed, and the poster then
waits OPEN_WAIT_S (30 s) before clicking again (a second click while the panel loads would close it). Now a tip card
found while the box is missing is dismissed and the panel is opened again at once. Captions are retried, with a stage
line, never silently. The camera frame is 960 x 540 (lighter on the bot's two vCPUs, still crisp)."""

import asyncio
import logging
from contextlib import asynccontextmanager

from bot import selectors as S
from bot.chat import ChatPoster


class Box:
    def __init__(self):
        self.value = ""

    async def fill(self, text, timeout=None):
        self.value = text

    async def press(self, key, timeout=None):
        self.value = ""

    async def input_value(self, timeout=None):
        return self.value

    async def count(self):
        return 1


class CardOverChat:
    """A Meet page where a tip card is up after the join: it swallows clicks until it is dismissed."""

    def __init__(self):
        self.card, self.panel, self.box, self.dismissed = True, False, Box(), 0
        self.ui = self

    @asynccontextmanager
    async def section(self, name):
        yield

    async def find(self, selector):
        return self.box if selector is S.CHAT_INPUT and self.panel else None

    async def click(self, selector):
        if self.card:
            return False  # the card takes the click
        if selector is S.CHAT_OPEN:
            self.panel = True
        if selector is S.CHAT_SEND:
            self.box.value = ""
        return True

    async def dismiss_tips(self):
        if not self.card:
            return False
        self.card, self.dismissed = False, self.dismissed + 1
        return True

    async def selector_miss(self, selector):
        pass


def test_JOIN_a_tip_card_over_the_chat_is_dismissed_and_the_intro_goes_out_at_once():
    page = CardOverChat()

    async def run():
        return await asyncio.wait_for(ChatPoster(page).send("Hi, I'm Tilo"), timeout=5)  # not the 30 s wait

    assert asyncio.run(run()) is True and page.dismissed == 1 and page.panel


def test_JOIN_a_card_that_keeps_coming_back_never_toggles_the_panel_in_a_loop(monkeypatch):
    page = CardOverChat()
    opens = []

    async def stubborn():
        return True  # a card is always there

    async def click(selector):
        if selector is S.CHAT_OPEN:
            opens.append(1)
        return False

    page.dismiss_tips, page.click = stubborn, click
    monkeypatch.setattr(ChatPoster, "OPEN_WAIT_S", 1.0)
    assert asyncio.run(ChatPoster(page)._open_box()) is None
    assert len(opens) <= 1 + ChatPoster.REOPENS  # the first open and at most REOPENS more, then the normal wait


def test_JOIN_captions_are_retried_with_a_stage_line_never_silently(caplog):
    from bot.session import enable_captions_with_retry  # noqa: PLC0415

    tries = []

    class Page:
        async def enable_captions(self):
            tries.append(1)
            return len(tries) == 2

        async def dismiss_tips(self):
            return True

    with caplog.at_level(logging.WARNING, logger="bot.cloud_run"):
        assert asyncio.run(enable_captions_with_retry(Page())) is True
    assert len(tries) == 2
    assert [r.getMessage() for r in caplog.records] == ["stage captions_retry attempt=2"]
