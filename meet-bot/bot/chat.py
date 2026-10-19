"""Posting into the Meet chat panel. Transport only; what may be said, and when, is decided by brain.ChatPolicy."""

from __future__ import annotations

import asyncio
import logging
import time

from . import selectors as S
from .ui import CHAT_POST

log = logging.getLogger("bot.chat")

INTRO = "Hi, I'm an AI assistant taking notes for this meeting."
INTRO_RECORDING = INTRO[:-1] + " (audio is being recorded locally for testing)."


def intro_text(recording: bool, hybrid: bool, voice: bool = False) -> str:
    """The disclosure must match what is really happening to the audio."""
    notes = []
    if hybrid:
        notes.append("audio is transcribed by an AI service")
    if recording:
        notes.append("audio is recorded locally for testing")
    if voice:
        notes.append("I may answer questions out loud and in chat")
    return INTRO[:-1] + (f" ({'; '.join(notes)}).") if notes else INTRO


STEP_TIMEOUT_MS = 3000  # a stale box must not hold the UI for Playwright's default 30 s


class ChatPoster:
    """Every step holds the UI only for one short action; waiting and polling happen outside it, so the mic can cut in."""

    SETTLE_S = 1.6  # how long Meet may take to clear the box after Send

    def __init__(self, browser) -> None:  # browser: bot.browser.MeetBrowser
        self.b = browser

    async def send(self, text: str) -> bool:
        for attempt in range(3):
            box = await self._open_box()
            if box is None:
                log.warning("chat input not found (attempt %d)", attempt + 1)
                await asyncio.sleep(1)
                continue
            try:
                async with self.b.ui.section(CHAT_POST):
                    await box.fill(text, timeout=STEP_TIMEOUT_MS)  # focuses the box itself
                async with self.b.ui.section(CHAT_POST):
                    if not await self.b.click(S.CHAT_SEND):
                        await box.press("Enter", timeout=STEP_TIMEOUT_MS)
                if await self._box_cleared(box):
                    log.info("chat posted: %s", text)
                    return True
                async with self.b.ui.section(CHAT_POST):  # text still in the box: not sent
                    await box.fill("", timeout=STEP_TIMEOUT_MS)
            except Exception as e:
                log.warning("chat send error: %s", e)
        await self.b.selector_miss(S.CHAT_INPUT)
        return False

    async def _open_box(self):
        """The chat box, opening the panel first if it is closed. Polls between short sections, never inside one."""
        opened = False
        for _ in range(14):
            async with self.b.ui.section(CHAT_POST):
                box = await self.b.find(S.CHAT_INPUT)
                if box is None and not opened:
                    await self.b.click(S.CHAT_OPEN)
                    await self.b.click(S.GOT_IT)  # first-open info dialog
                    opened = True
            if box is not None:
                return box
            await asyncio.sleep(0.3)
        return None

    async def _box_cleared(self, box) -> bool:
        deadline = time.monotonic() + self.SETTLE_S
        while True:
            async with self.b.ui.section(CHAT_POST):
                left = await box.input_value(timeout=STEP_TIMEOUT_MS) if await box.count() else ""
            if not left.strip():
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.1)
