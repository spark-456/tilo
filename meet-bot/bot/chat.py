"""Posting into the Meet chat panel. Transport only; what may be said, and when, is decided by brain.ChatPolicy."""

from __future__ import annotations

import asyncio
import logging

from . import selectors as S

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


class ChatPoster:
    def __init__(self, browser) -> None:  # browser: bot.browser.MeetBrowser
        self.b = browser

    async def send(self, text: str) -> bool:
        async with self.b.lock:
            return await self._send(text)

    async def _send(self, text: str) -> bool:
        for attempt in range(3):
            box = await self.b.find(S.CHAT_INPUT)
            if box is None:
                await self.b.click(S.CHAT_OPEN, timeout_s=3)
                await self.b.click(S.GOT_IT)  # first-open info dialog
                box = await self.b.find(S.CHAT_INPUT, timeout_s=4)
            if box is None:
                log.warning("chat input not found (attempt %d)", attempt + 1)
                await asyncio.sleep(1)
                continue
            try:
                await box.click()
                await box.fill(text)
                if not await self.b.click(S.CHAT_SEND):
                    await self.b.page.keyboard.press("Enter")
                await asyncio.sleep(0.8)
                left = await box.input_value() if await box.count() else ""
                if left.strip():  # text still in the box: not sent
                    await box.fill("")
                    continue
                log.info("chat posted: %s", text)
                return True
            except Exception as e:
                log.warning("chat send error: %s", e)
        await self.b.selector_miss(S.CHAT_INPUT)
        return False
