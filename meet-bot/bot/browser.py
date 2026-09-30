"""Drives headed Chromium the way a person would. All selectors come from selectors.py."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import selectors as S
from .config import Config
from .people import clean_name as _clean_name
from .people import name_match as _name_match

log = logging.getLogger("bot.browser")

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=Translate,MediaRouter,OptimizationHints",
    "--disable-smooth-scrolling",
    "--autoplay-policy=no-user-gesture-required",
    "--no-first-run",
    "--no-default-browser-check",
    "--lang=en-US",
    "--window-size=1280,720",
    "--window-position=0,0",
]


class NotLoggedIn(RuntimeError):
    pass


class JoinFailed(RuntimeError):
    pass


def clean_singleton_locks(profile: Path) -> None:
    """A killed container leaves Chromium's lock files behind, which blocks the next launch."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = profile / name
        if p.is_symlink() or p.exists():
            p.unlink(missing_ok=True)


def locate(page: Any, strat: S.Strategy) -> Any:
    kind = strat[0]
    if kind == "role":
        return page.get_by_role(strat[1], name=re.compile(strat[2], re.I))
    if kind == "text":
        return page.get_by_text(re.compile(strat[1], re.I))
    if kind == "placeholder":
        return page.get_by_placeholder(re.compile(strat[1], re.I))
    if kind == "aria":
        return page.locator(f'[aria-label*="{strat[1]}" i]')
    if kind == "aria_region":
        return page.locator(f'[role="region"][aria-label*="{strat[1]}" i]')
    raise ValueError(f"unknown selector strategy {kind!r}")


class MeetBrowser:
    def __init__(self, cfg: Config, voice: bool = False) -> None:
        self.cfg = cfg
        self.voice = voice  # a virtual microphone exists: let Meet use it without a permission prompt
        self.lock = asyncio.Lock()  # one UI action at a time (mic toggles and chat typing must not interleave)
        self.page: Any = None
        self.ctx: Any = None
        self._pw: Any = None
        self.account_name: str | None = None
        self._shot_n = 0

    # -- lifecycle -----------------------------------------------------------------------------------------------
    async def __aenter__(self) -> MeetBrowser:
        from playwright.async_api import async_playwright

        self.cfg.debug_dir.mkdir(parents=True, exist_ok=True)
        clean_singleton_locks(self.cfg.profile_dir)
        self._pw = await async_playwright().start()
        self.ctx = await self._pw.chromium.launch_persistent_context(
            str(self.cfg.profile_dir),
            headless=False,
            args=CHROMIUM_ARGS + (["--use-fake-ui-for-media-stream"] if self.voice else []),
            ignore_default_args=["--enable-automation", "--mute-audio"],
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        try:
            if self.ctx:
                await self.ctx.close()
        finally:
            if self._pw:
                await self._pw.stop()

    # -- helpers -------------------------------------------------------------------------------------------------
    async def shot(self, label: str) -> Path:
        self._shot_n += 1
        path = self.cfg.debug_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{self._shot_n:02d}_{label}.png"
        try:
            await self.page.screenshot(path=str(path))
        except Exception as e:
            log.warning("screenshot %s failed: %s", label, e)
        return path

    async def find(self, sel: S.Sel, timeout_s: float = 0.0) -> Any | None:
        """First visible match over the selector's strategies, polling up to timeout_s. None if not found."""
        deadline = time.monotonic() + timeout_s
        while True:
            for strat in sel.strategies:
                try:
                    loc = locate(self.page, strat).first
                    if await loc.is_visible():
                        return loc
                except Exception:
                    continue
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.3)

    async def visible(self, sel: S.Sel) -> bool:
        return await self.find(sel) is not None

    async def click(self, sel: S.Sel, timeout_s: float = 0.0, required: bool = False) -> bool:
        loc = await self.find(sel, timeout_s)
        if loc is None:
            if required:
                await self.selector_miss(sel)
            return False
        try:
            await loc.click(timeout=5000)
            return True
        except Exception as e:
            log.warning("click on %s failed: %s", sel.name, e)
            await self.selector_miss(sel)
            return False

    async def selector_miss(self, sel: S.Sel) -> None:
        path = await self.shot(f"selector-miss_{sel.name}")
        log.warning("selector '%s' did not match; screenshot %s", sel.name, path)

    # -- account -------------------------------------------------------------------------------------------------
    def _check_url_login(self) -> None:
        if any(h in self.page.url for h in S.LOGIN_HOSTS):
            raise NotLoggedIn("The browser profile is not signed in. Run `login` and sign in through noVNC first.")

    async def check_account(self) -> None:
        """Sanity-check the signed-in account against BOT_GOOGLE_EMAIL (label only, never authentication)."""
        loc = await self.find(S.ACCOUNT_BUTTON, 3)
        if loc is None:
            log.warning("could not read the signed-in account label (selector 'account_button')")
            return
        label = (await loc.get_attribute("aria-label")) or ""
        m = re.search(r"[\w.+-]+@[\w.-]+", label)
        nm = re.match(r"Google Account:\s*(.+?)\s*[\n(]", label)
        if nm:
            self.account_name = nm.group(1).strip()
        if m and self.cfg.bot_email and m.group(0).lower() != self.cfg.bot_email.lower():
            log.warning("signed in as %s but BOT_GOOGLE_EMAIL is %s", m.group(0), self.cfg.bot_email)
        elif m:
            log.info("signed in as %s", m.group(0))

    # -- open / join ---------------------------------------------------------------------------------------------
    async def open_new_meeting(self) -> str:
        await self.page.goto(S.MEET_NEW_URL, wait_until="domcontentloaded")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._check_url_login()
            if m := S.MEETING_URL_RE.match(self.page.url):
                await self.shot("01_new_meeting_created")
                return m.group(0)
            await asyncio.sleep(1)
        await self.shot("new_meeting_timeout")
        raise JoinFailed("meet.google.com/new did not produce a meeting link within 60 s")

    async def open_meeting(self, url: str) -> None:
        if not S.MEETING_URL_RE.match(url):
            raise JoinFailed(f"not a Meet link: {url}")
        await self.page.goto(url, wait_until="domcontentloaded")
        self._check_url_login()

    async def join(self) -> bool:
        """Pre-join: no mic/camera, press join. Returns True if the bot had to ask to join."""
        asked = False
        deadline = time.monotonic() + self.cfg.join_timeout_s
        shot_done = False
        while time.monotonic() < deadline:
            self._check_url_login()
            if await self.visible(S.LEAVE_CALL):  # host via /new lands straight in the call, no pre-join screen
                await self.check_account()
                await self._after_join()
                return False
            await self.click(S.CONTINUE_WITHOUT_MEDIA)
            await self.click(S.GOT_IT)
            await self.click(S.MIC_TURN_OFF)  # only visible when the mic is on
            await self.click(S.CAM_TURN_OFF)
            if not shot_done and (await self.visible(S.JOIN_NOW) or await self.visible(S.ASK_TO_JOIN)):
                await self.check_account()
                await self.shot("02_prejoin_mic_cam_off")
                shot_done = True
            if await self.click(S.JOIN_NOW):
                break
            if await self.click(S.ASK_TO_JOIN):
                asked = True
                break
            await asyncio.sleep(1)
        else:
            await self.selector_miss(S.JOIN_NOW)
            raise JoinFailed("could not find a Join / Ask to join button on the pre-join screen")
        await self._wait_in_call(asked)
        return asked

    async def _after_join(self) -> None:
        await self.click(S.CLOSE_DIALOG, timeout_s=2)  # "Your meeting's ready" card
        await self.shot("03_in_call")

    async def _wait_in_call(self, asked: bool) -> None:
        timeout = self.cfg.ask_to_join_timeout_s if asked else self.cfg.join_timeout_s
        deadline = time.monotonic() + timeout
        waiting_shot = False
        while time.monotonic() < deadline:
            if await self.visible(S.LEAVE_CALL):
                await self._after_join()
                return
            if await self.visible(S.DENIED_TEXT):
                await self.shot("join_denied")
                raise JoinFailed("the host denied the request to join")
            if not waiting_shot and await self.visible(S.WAITING_TEXT):
                waiting_shot = True
                log.info("waiting to be let in (timeout %.0fs)", timeout)
                await self.shot("02b_waiting_to_be_admitted")
            await asyncio.sleep(1)
        await self.shot("join_timeout")
        raise JoinFailed(f"not in the call after {timeout:.0f}s (waiting for admission?)")

    # -- in call -------------------------------------------------------------------------------------------------
    async def enable_captions(self) -> bool:
        for attempt in range(3):
            if await self.visible(S.CAPTIONS_OFF):  # already on
                return True
            if await self.click(S.CAPTIONS_ON, timeout_s=3):
                break
            log.info("captions button not found (attempt %d); trying the 'c' shortcut", attempt + 1)
            await self.page.keyboard.press("c")
            await asyncio.sleep(1.5)
            if await self.visible(S.CAPTIONS_OFF):
                return True
        await asyncio.sleep(1.5)
        ok = await self.visible(S.CAPTIONS_OFF) or await self.visible(S.CAPTIONS_REGION)
        await self.shot("04_captions_on" if ok else "captions_failed")
        if not ok:
            await self.selector_miss(S.CAPTIONS_ON)
        return ok

    async def people_count(self) -> int | None:
        loc = await self.find(S.PEOPLE_BUTTON)
        if loc is None:
            return None
        text = ((await loc.inner_text()) or "") + " " + ((await loc.get_attribute("aria-label")) or "")
        nums = re.findall(r"\b(\d{1,3})\b", text)
        return int(nums[0]) if nums else None

    async def meeting_ended(self) -> bool:
        if not self.page.url.startswith("https://meet.google.com/") or not S.MEETING_URL_RE.match(self.page.url):
            return True
        if await self.visible(S.ENDED_TEXT):
            return True
        try:  # nudge the mouse so an auto-hidden toolbar comes back before we judge
            await self.page.mouse.move(random.randint(200, 900), random.randint(150, 500))
        except Exception:
            pass
        return not await self.visible(S.LEAVE_CALL)

    async def leave(self) -> None:
        try:
            if await self.click(S.LEAVE_CALL):
                await asyncio.sleep(1.5)
            await self.shot("99_left_meeting")
        except Exception as e:
            log.warning("clean leave failed (%s); closing the browser instead", e)

    # -- people ----------------------------------------------------------------------------------------------------
    async def admit_waiting(self, allowed: list[str]) -> list[str]:
        """Admit people waiting to join. With an allowlist only matching names are admitted; else everyone."""
        admitted: list[str] = []
        try:
            if not await self.visible(S.ADMIT_BUTTON):
                if await self.visible(S.ADMIT_PILL):  # top-right "Admit N guest(s)" opens the People panel
                    await self.click(S.ADMIT_PILL)
                    await asyncio.sleep(1.2)
            for strat in S.ADMIT_BUTTON.strategies:
                buttons = locate(self.page, strat)
                n = await buttons.count()
                for i in reversed(range(n)):
                    btn = buttons.nth(i)
                    if not await btn.is_visible():
                        continue
                    row = await btn.evaluate(S.ROW_TEXT_JS)
                    name = _clean_name(row.splitlines()[0]) if row else "guest"
                    if allowed and not any(_name_match(a, name) for a in allowed):
                        log.warning("not admitting %r: not on the allowlist", name)
                        continue
                    await btn.click(timeout=5000)
                    log.info("admitted %s", name)
                    admitted.append(name)
                    await asyncio.sleep(0.5)
                if admitted:
                    return admitted
            if await self.visible(S.WAITING_MARK):  # people wait but no strategy matched: click by leaf text
                for row in await self.page.evaluate(S.ADMIT_CLICK_JS, [a.lower() for a in allowed]):
                    name = _clean_name(row.splitlines()[0]) if row else "guest"
                    log.info("admitted %s (fallback click)", name)
                    admitted.append(name)
                if not admitted:
                    await self._dump("admit_dom")
                    log.warning("someone is waiting but no matching Admit control; page text saved to debug/")
        except Exception as e:
            log.warning("admit failed: %s", e)
        return admitted

    async def _dump(self, label: str) -> None:
        if label in getattr(self, "_dumped", set()):
            return
        self._dumped = getattr(self, "_dumped", set()) | {label}
        try:
            html = await self.page.evaluate("() => document.body.innerText.slice(0, 4000)")
            (self.cfg.debug_dir / f"{label}.txt").write_text(html, encoding="utf-8")
            await self.shot(label)
        except Exception:
            pass

    async def participants(self) -> dict[str, Any] | None:
        """{'others': [...], 'waiting': [...], 'self': name|None} read from the People panel, or None if unreadable."""
        try:
            if not await self.visible(S.PEOPLE_PANEL_MARK):
                if not await self.click(S.PEOPLE_BUTTON):
                    return None
                await asyncio.sleep(1.2)
            rows = await self.page.evaluate(S.PARTICIPANTS_JS)
        except Exception as e:
            log.warning("could not read participants: %s", e)
            return None
        out: dict[str, Any] = {"others": [], "waiting": [], "self": None}
        for row in rows:
            lines = [ln.strip() for ln in row["text"].splitlines() if ln.strip()]
            if not lines:
                continue
            name = _clean_name(lines[0])
            if not name:
                continue
            if row["waiting"]:
                out["waiting"].append(name)
            elif any("(you)" in ln.lower() for ln in lines):
                out["self"] = name
            else:
                out["others"].append(name)
        return out

    # -- chat reading ----------------------------------------------------------------------------------------------
    async def show_chat(self) -> None:
        """Make the chat panel the visible side panel (reading the People panel replaces it)."""
        if not await self.visible(S.CHAT_INPUT):
            await self.click(S.CHAT_OPEN)
            await asyncio.sleep(0.6)

    async def read_chat(self) -> list[tuple[str, str]] | None:
        """[(sender, text)] for every message currently in the chat panel, or None if the panel is not open."""
        from .chatread import parse_chat_panel

        try:
            data = await self.page.evaluate(S.CHAT_READ_JS)
        except Exception as e:
            log.warning("could not read chat: %s", e)
            return None
        if data["panelText"] is None:
            return None
        msgs = [(i["sender"] or "?", i["text"]) for i in data["items"] if i["text"]]
        if not msgs:
            msgs = parse_chat_panel(data["panelText"])
        if msgs and data["panelHtml"] and not getattr(self, "_chat_dumped", False):
            self._chat_dumped = True
            (self.cfg.debug_dir / "chat_panel.html").write_text(data["panelHtml"], encoding="utf-8")
            (self.cfg.debug_dir / "chat_panel.txt").write_text(data["panelText"], encoding="utf-8")
        return msgs

    # -- microphone (the bot's own, for voice replies) ---------------------------------------------------------------
    async def set_mic(self, on: bool) -> bool:
        """Make the bot's Meet microphone on/off. True if it ended in the requested state."""
        async with self.lock:
            now_on = await self.visible(S.MIC_TURN_OFF)  # the button says "Turn off" when the mic is currently on
            if now_on == on and (on or await self.visible(S.MIC_TURN_ON)):
                return True
            if not await self.click(S.MIC_TURN_OFF if not on else S.MIC_TURN_ON, timeout_s=1.5):
                await self.page.keyboard.press("Control+d")  # Meet's shortcut for the mic
            await asyncio.sleep(0.25)
            ok = await self.visible(S.MIC_TURN_OFF) == on
            if not ok:
                await self.selector_miss(S.MIC_TURN_ON if on else S.MIC_TURN_OFF)
            return ok
